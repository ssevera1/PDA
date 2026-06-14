"""Twilio voice webhook — Media Streams + xAI Voice Agent bridge."""

from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter, Request, Response, HTTPException, WebSocket

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
    if store.active_count() >= MAX_CONCURRENT_CALLS:
        return _twiml(
            '<Say voice="Polly.Matthew-Neural">All lines are busy. Please try again later.</Say>'
            "<Hangup/>"
        )

    form = await request.form()
    form_data = dict(form)
    _verify_signature(request, form_data)

    settings = get_settings()
    call_sid = _sanitize(form_data.get("CallSid", ""), max_len=50) or "unknown"
    caller = _sanitize(form_data.get("From", "unknown"), max_len=100) or "unknown"

    store.create(
        call_sid=call_sid,
        caller=caller,
        caller_city=_sanitize(form_data.get("FromCity"), max_len=100),
        caller_state=_sanitize(form_data.get("FromState"), max_len=50),
    )

    ws_base = settings.base_url.replace("https://", "wss://").replace("http://", "ws://")
    stream_url = f"{ws_base}/voice/media-stream"

    return _twiml(f'<Connect><Stream url="{stream_url}"/></Connect>')


@router.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """Twilio Media Stream endpoint — bridges audio to the xAI Voice Agent."""
    await websocket.accept()

    call_sid: str | None = None
    session = None

    try:
        stream_sid: str | None = None

        # Consume Twilio's initial handshake to get callSid and streamSid
        async for raw in websocket.iter_text():
            data = json.loads(raw)
            event = data.get("event")
            if event == "connected":
                continue
            if event == "start":
                call_sid = data["start"]["callSid"]
                stream_sid = data["start"]["streamSid"]
                session = store.get(call_sid)
                break

        if session is None or stream_sid is None:
            logger.warning(f"No session found for call_sid={call_sid} — closing")
            await websocket.close()
            return

        bridge = XAIVoiceBridge(
            twilio_ws=websocket,
            session=session,
            stream_sid=stream_sid,
        )
        await bridge.run()

    except Exception:
        logger.exception(f"Media stream error for call {call_sid}")
    finally:
        if session:
            try:
                summary = await summarize_call(session)
                await send_notifications(session, summary)
            except Exception:
                logger.exception(f"Post-call summary failed for {call_sid}")
            store.remove(call_sid)


@router.post("/status")
async def call_status(request: Request):
    """Twilio status callback — safety net for calls that end without a clean bridge exit."""
    form = await request.form()
    form_data = dict(form)
    _verify_signature(request, form_data)

    call_sid = form_data.get("CallSid", "")
    logger.info(f"Status callback: {call_sid} -> {form_data.get('CallStatus', '')}")

    session = store.get(call_sid)
    if session is None:
        # Already cleaned up by the WebSocket handler — normal path
        return Response(status_code=204)

    if session.messages:
        try:
            summary = await summarize_call(session)
            await send_notifications(session, summary)
        except Exception:
            logger.exception(f"Status-callback summary failed for {call_sid}")

    store.remove(call_sid)
    return Response(status_code=204)
