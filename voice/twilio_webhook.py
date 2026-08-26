"""Twilio voice webhook — Media Streams + xAI Voice Agent bridge."""

from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter, Request, Response, HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from twilio.request_validator import RequestValidator

from config import get_settings
from store.conversations import store
from agent.brain import summarize_call
from notifications.dispatcher import send_notifications
from voice.xai_bridge import XAIVoiceBridge

logger = logging.getLogger("pdagent.voice")

router = APIRouter(prefix="/voice", tags=["voice"])

MAX_CONCURRENT_CALLS = 10


def _twiml(content: str) -> Response:
    return Response(
        content=f'<?xml version="1.0" encoding="UTF-8"?><Response>{content}</Response>',
        media_type="application/xml",
    )


def _sanitize(value: str | None, max_len: int = 100) -> str | None:
    if value is None:
        return None
    value = str(value)[:max_len].strip()
    value = re.sub(r"[\r\n]", " ", value)
    return value or None


def _verify_signature(request: Request, form_data: dict) -> None:
    settings = get_settings()
    validator = RequestValidator(settings.twilio_auth_token)
    signature = request.headers.get("X-Twilio-Signature", "")
    if not validator.validate(str(request.url), form_data, signature):
        logger.warning("Invalid Twilio signature — rejecting request")
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


@router.post("/incoming")
async def incoming_call(request: Request):
    """Accept an incoming call and open a Twilio Media Stream to the xAI bridge."""
    try:
        if store.active_count() >= MAX_CONCURRENT_CALLS:
            logger.warning(f"Max concurrent calls ({MAX_CONCURRENT_CALLS}) reached")
            return _twiml(
                '<Say voice="Polly.Matthew-Neural">All lines are busy. Please try again later.</Say>'
                "<Hangup/>"
            )

        form = await request.form()
        form_data = dict(form)
    except Exception as e:
        logger.error(f"Failed to parse incoming call form: {e}", exc_info=True)
        return _twiml(
            '<Say voice="Polly.Matthew-Neural">An error occurred. Please try again.</Say>'
            "<Hangup/>"
        )

    try:
        _verify_signature(request, form_data)
    except HTTPException as e:
        # Fail closed: an unsigned/forged request must stay a 4xx so WAFs,
        # alerting and rate limiters can still see spoofing attempts.
        logger.error(f"Signature verification failed: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Signature verification error: {e}", exc_info=True)
        return Response(status_code=500)

    try:
        settings = get_settings()
        call_sid = _sanitize(form_data.get("CallSid", ""), max_len=50) or "unknown"
        caller = _sanitize(form_data.get("From", "unknown"), max_len=100) or "unknown"

        if call_sid == "unknown":
            logger.error("Incoming call missing CallSid — cannot create session")
            return _twiml(
                '<Say voice="Polly.Matthew-Neural">An error occurred. Please try again.</Say>'
                "<Hangup/>"
            )

        store.create(
            call_sid=call_sid,
            caller=caller,
            caller_city=_sanitize(form_data.get("FromCity"), max_len=100),
            caller_state=_sanitize(form_data.get("FromState"), max_len=50),
        )

        logger.info(f"Incoming call created: {call_sid} from {caller}")

        ws_base = settings.base_url.replace("https://", "wss://").replace("http://", "ws://")
        stream_url = f"{ws_base}/voice/media-stream"

        return _twiml(f'<Connect><Stream url="{stream_url}"/></Connect>')
    except Exception as e:
        logger.error(f"Incoming call handler error: {e}", exc_info=True)
        return _twiml(
            '<Say voice="Polly.Matthew-Neural">An error occurred. Please try again.</Say>'
            "<Hangup/>"
        )


@router.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """Twilio Media Stream endpoint — bridges audio to the xAI Voice Agent."""
    call_sid: str | None = None
    session = None

    try:
        await websocket.accept()
    except Exception as e:
        logger.error(f"WebSocket accept failed: {e}", exc_info=True)
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except Exception:
            pass
        return

    try:
        stream_sid: str | None = None

        # Consume Twilio's initial handshake to get callSid and streamSid
        async for raw in websocket.iter_text():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                # No exc_info/ERROR here: a client spraying garbage would
                # otherwise emit an unbounded stream of full tracebacks.
                logger.warning(f"Malformed JSON from Twilio: {e}")
                continue

            if not isinstance(data, dict):
                logger.warning(f"Non-object frame from Twilio: {type(data).__name__}")
                continue

            event = data.get("event")
            if event == "connected":
                continue
            if event == "start":
                try:
                    call_sid = data["start"]["callSid"]
                    stream_sid = data["start"]["streamSid"]
                except (KeyError, TypeError) as e:
                    logger.error(f"Missing required fields in start event: {e}", exc_info=True)
                    await websocket.close(code=1002, reason="Invalid start event")
                    return

                session = store.get(call_sid)
                break

        if session is None or stream_sid is None:
            logger.warning(f"No session found or missing stream_sid for call_sid={call_sid} — closing")
            try:
                await websocket.close(code=1008, reason="Session not found")
            except Exception:
                pass
            return

        logger.info(f"Media stream started: {call_sid} stream={stream_sid}")

        bridge = XAIVoiceBridge(
            twilio_ws=websocket,
            session=session,
            stream_sid=stream_sid,
        )
        await bridge.run()

    except WebSocketDisconnect as e:
        # Caller hung up — an expected end-of-call, not an error.
        logger.warning(f"WebSocket disconnected for call {call_sid}: {e}")
    except Exception as e:
        logger.error(f"Media stream error for call {call_sid}: {e}", exc_info=True)
    finally:
        if session:
            try:
                summary = await summarize_call(session)
                await send_notifications(session, summary)
            except Exception as e:
                logger.error(f"Post-call summary failed for {call_sid}: {e}", exc_info=True)
            try:
                store.remove(call_sid)
            except Exception as e:
                logger.error(f"Failed to remove session {call_sid}: {e}", exc_info=True)
        else:
            if call_sid:
                logger.warning(f"Media stream closed without session for {call_sid}")


@router.post("/status")
async def call_status(request: Request):
    """Twilio status callback — safety net for calls that end without a clean bridge exit."""
    try:
        form = await request.form()
        form_data = dict(form)
    except Exception as e:
        logger.error(f"Failed to parse status callback form: {e}", exc_info=True)
        return Response(status_code=400)

    try:
        _verify_signature(request, form_data)
    except HTTPException:
        logger.warning("Status callback signature verification failed")
        return Response(status_code=403)
    except Exception as e:
        logger.error(f"Status callback signature error: {e}", exc_info=True)
        return Response(status_code=500)

    call_sid = form_data.get("CallSid", "")
    call_status = form_data.get("CallStatus", "unknown")

    if not call_sid:
        logger.warning("Status callback received without CallSid")
        return Response(status_code=204)

    logger.info(f"Status callback: {call_sid} -> {call_status}")

    try:
        session = store.get(call_sid)
        if session is None:
            logger.debug(f"Status callback for unknown session {call_sid} — already cleaned up")
            return Response(status_code=204)

        if session.messages:
            try:
                summary = await summarize_call(session)
                await send_notifications(session, summary)
            except Exception as e:
                logger.error(f"Status-callback summary failed for {call_sid}: {e}", exc_info=True)

        store.remove(call_sid)
    except Exception as e:
        logger.error(f"Status callback handler error for {call_sid}: {e}", exc_info=True)

    return Response(status_code=204)
