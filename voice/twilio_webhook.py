"""Twilio TwiML webhook handler for voice calls."""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from fastapi import APIRouter, Request, Response, HTTPException
from twilio.request_validator import RequestValidator

from config import get_settings
from store.conversations import store
from agent.brain import respond, generate_greeting, summarize_call
from notifications.dispatcher import send_notifications

logger = logging.getLogger("pdagent.voice")

router = APIRouter(prefix="/voice", tags=["voice"])

MAX_TURNS = 20
MAX_CONCURRENT_CALLS = 10


def _twiml_response(twiml: str) -> Response:
    """Return a TwiML XML response."""
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response>{twiml}</Response>'
    return Response(content=xml, media_type="application/xml")


def _say(text: str) -> str:
    """Wrap text in a <Say> verb with Polly voice."""
    # Escape XML special characters
    safe = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return f'<Say voice="Polly.Joanna">{safe}</Say>'


def _gather_with_say(text: str, action_path: str, base_url: str) -> str:
    """Build <Gather> with <Say> inside, pointing to action URL."""
    action_url = urljoin(base_url, action_path)
    return (
        f'<Gather input="speech" action="{action_url}" method="POST" '
        f'speechTimeout="auto">'
        f'{_say(text)}'
        f'</Gather>'
    )


def _sanitize_field(value: str | None, max_len: int = 100) -> str | None:
    """Sanitize caller-controlled fields: strip, truncate, remove newlines."""
    if value is None:
        return None
    value = str(value)[:max_len].strip()
    value = re.sub(r"[\r\n]", " ", value)
    return value or None


def _validate_twilio_signature(request: Request, form_data: dict) -> None:
    """Verify the X-Twilio-Signature header using the auth token."""
    settings = get_settings()
    validator = RequestValidator(settings.twilio_auth_token)

    # Reconstruct the full URL Twilio used to sign
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)

    if not validator.validate(url, form_data, signature):
        logger.warning("Invalid Twilio signature — rejecting request")
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


@router.post("/incoming")
async def incoming_call(request: Request):
    """Handle an incoming call from Twilio.

    Creates a session, generates a greeting, returns TwiML with
    <Say> + <Gather> to begin the conversation loop.
    """
    if store.active_count() >= MAX_CONCURRENT_CALLS:
        return _twiml_response(
            _say("I'm sorry, all lines are busy. Please try again later.")
            + "<Hangup/>"
        )

    form = await request.form()
    form_data = dict(form)
    _validate_twilio_signature(request, form_data)

    settings = get_settings()
    call_sid = _sanitize_field(form_data.get("CallSid", ""), max_len=50) or "unknown"
    caller = _sanitize_field(form_data.get("From", "unknown"), max_len=100) or "unknown"
    caller_city = _sanitize_field(form_data.get("FromCity"), max_len=100)
    caller_state = _sanitize_field(form_data.get("FromState"), max_len=50)

    session = store.create(
        call_sid=call_sid,
        caller=caller,
        caller_city=caller_city,
        caller_state=caller_state,
    )

    greeting = await generate_greeting(session)
    spoken = greeting.replace("CALL_COMPLETE", "").strip()

    twiml = _gather_with_say(spoken, "/voice/gather", settings.base_url)
    return _twiml_response(twiml)


@router.post("/gather")
async def gather_speech(request: Request):
    """Handle gathered speech from the caller.

    Runs the caller's speech through the LLM and returns TwiML with
    the agent's reply. Ends the call on CALL_COMPLETE or turn limit.
    """
    form = await request.form()
    form_data = dict(form)
    _validate_twilio_signature(request, form_data)

    settings = get_settings()
    call_sid = form_data.get("CallSid", "")
    session = store.get(call_sid)

    if session is None:
        logger.warning(f"Gather for unknown session: {call_sid}")
        return _twiml_response(
            _say("I'm sorry, something went wrong. Goodbye.") + "<Hangup/>"
        )

    caller_said = (form_data.get("SpeechResult") or "").strip()
    if not caller_said:
        # No speech detected — re-prompt
        twiml = _gather_with_say(
            "I'm sorry, I didn't catch that. Could you say that again?",
            "/voice/gather",
            settings.base_url,
        )
        return _twiml_response(twiml)

    # Enforce turn limit
    turn_count = sum(1 for m in session.messages if m["role"] == "user")
    if turn_count >= MAX_TURNS:
        goodbye = (
            "I appreciate your patience. I've taken note of everything, "
            "and I'll make sure to pass along a detailed message. "
            "Thank you so much for calling. Goodbye!"
        )
        twiml = _say(goodbye) + "<Hangup/>"

        # Summarize and notify
        try:
            summary = await summarize_call(session)
            await send_notifications(session, summary)
        except Exception:
            logger.exception(f"Failed to summarize at turn limit: {call_sid}")
        finally:
            store.remove(call_sid)

        return _twiml_response(twiml)

    reply = await respond(session, caller_said)
    call_complete = "CALL_COMPLETE" in reply
    spoken = reply.replace("CALL_COMPLETE", "").strip()

    if call_complete:
        twiml = _say(spoken) + "<Hangup/>"

        # Summarize and notify
        try:
            summary = await summarize_call(session)
            await send_notifications(session, summary)
        except Exception:
            logger.exception(f"Failed to summarize completed call: {call_sid}")
        finally:
            store.remove(call_sid)

        return _twiml_response(twiml)

    # Continue conversation
    twiml = _gather_with_say(spoken, "/voice/gather", settings.base_url)
    return _twiml_response(twiml)


@router.post("/status")
async def call_status(request: Request):
    """Handle Twilio status callback.

    Called when the call ends. If the session still exists (caller hung up
    before CALL_COMPLETE), generate summary and send notification.
    """
    form = await request.form()
    form_data = dict(form)
    _validate_twilio_signature(request, form_data)

    call_sid = form_data.get("CallSid", "")
    call_status = form_data.get("CallStatus", "")
    logger.info(f"Status callback: {call_sid} -> {call_status}")

    session = store.get(call_sid)
    if session is None:
        # Already cleaned up (normal CALL_COMPLETE path)
        return Response(status_code=204)

    # Caller hung up mid-conversation — summarize and notify
    if len(session.messages) > 1:
        try:
            summary = await summarize_call(session)
            await send_notifications(session, summary)
            logger.info(f"Summary sent for hung-up call {call_sid}")
        except Exception:
            logger.exception(f"Failed to summarize hung-up call: {call_sid}")

    store.remove(call_sid)
    return Response(status_code=204)
