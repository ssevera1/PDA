from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import Gather, VoiceResponse

from config import get_settings
from store.conversations import store
from agent.brain import respond, generate_greeting, summarize_call
from notifications.telegram import send_call_summary

logger = logging.getLogger("pdagent.telephony")

router = APIRouter(prefix="/voice", tags=["telephony"])

VOICE = "Polly.Joanna"  # AWS Polly voice — natural-sounding female
MAX_TURNS = 20  # Cap conversation length to prevent runaway API costs


def _twiml(response: VoiceResponse) -> Response:
    return Response(content=str(response), media_type="application/xml")


def _mask_phone(number: str) -> str:
    """Mask phone number for logging: +1234567890 -> +1***7890"""
    if len(number) > 6:
        return number[:2] + "***" + number[-4:]
    return "***"


@router.post("/incoming")
async def handle_incoming_call(
    CallSid: str = Form(...),
    From: str = Form(...),
    CallerCity: str = Form(None),
    CallerState: str = Form(None),
):
    """Twilio hits this webhook when a call comes in."""
    logger.info(f"Incoming call {CallSid} from {_mask_phone(From)}")

    session = store.create(
        call_sid=CallSid,
        caller=From,
        caller_city=CallerCity,
        caller_state=CallerState,
    )

    greeting = await generate_greeting(session)
    # Strip any system signals from spoken text
    spoken = greeting.replace("CALL_COMPLETE", "").strip()

    vr = VoiceResponse()
    gather = Gather(
        input="speech",
        action="/voice/respond",
        method="POST",
        speech_timeout="auto",
        language="en-US",
    )
    gather.say(spoken, voice=VOICE)
    vr.append(gather)

    # If caller doesn't say anything, prompt again
    vr.say("I'm still here if you need anything. Just let me know.", voice=VOICE)
    vr.redirect("/voice/incoming", method="POST")

    return _twiml(vr)


@router.post("/respond")
async def handle_response(
    CallSid: str = Form(...),
    SpeechResult: str = Form(""),
    From: str = Form(...),
):
    """Twilio hits this after the caller speaks (Gather callback)."""
    session = store.get(CallSid)

    if not session:
        # Session expired or missing — create a recovery session
        session = store.create(call_sid=CallSid, caller=From)
        logger.warning(f"Recovered missing session for {CallSid}")

    caller_said = SpeechResult.strip()
    logger.info(f"[{CallSid}] Caller spoke ({len(caller_said)} chars)")

    if not caller_said:
        vr = VoiceResponse()
        gather = Gather(
            input="speech",
            action="/voice/respond",
            method="POST",
            speech_timeout="auto",
            language="en-US",
        )
        gather.say(
            "Sorry, I didn't catch that. Could you say that again?", voice=VOICE
        )
        vr.append(gather)
        return _twiml(vr)

    # Enforce conversation length limit
    turn_count = sum(1 for m in session.messages if m["role"] == "user")
    if turn_count >= MAX_TURNS:
        vr = VoiceResponse()
        vr.say(
            "I appreciate your patience. I've taken note of everything, "
            "and I'll make sure to pass along a detailed message. "
            "Thank you so much for calling. Goodbye!",
            voice=VOICE,
        )
        vr.hangup()
        return _twiml(vr)

    # Get AI response
    reply = await respond(session, caller_said)
    call_complete = "CALL_COMPLETE" in reply
    spoken = reply.replace("CALL_COMPLETE", "").strip()

    vr = VoiceResponse()

    if call_complete:
        # End the call gracefully
        vr.say(spoken, voice=VOICE)
        vr.pause(length=1)
        vr.hangup()
    else:
        # Continue the conversation
        gather = Gather(
            input="speech",
            action="/voice/respond",
            method="POST",
            speech_timeout="auto",
            language="en-US",
        )
        gather.say(spoken, voice=VOICE)
        vr.append(gather)

        # Fallback if no speech detected
        vr.say("Are you still there?", voice=VOICE)
        vr.redirect(f"/voice/respond?CallSid={CallSid}", method="POST")

    return _twiml(vr)


@router.post("/status")
async def handle_call_status(
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: str = Form(None),
):
    """Twilio status callback — fires when call ends."""
    logger.info(f"Call {CallSid} status: {CallStatus}")

    if CallStatus != "completed":
        store.remove(CallSid)
        return {"ok": True}

    session = store.get(CallSid)
    if not session or len(session.messages) <= 1:
        # No real conversation happened
        store.remove(CallSid)
        return {"ok": True}

    # Generate summary and notify
    try:
        summary = await summarize_call(session)
        await send_call_summary(session, summary)
        logger.info(f"Summary sent for call {CallSid}")
    except Exception:
        logger.exception(f"Failed to send summary for call {CallSid}")
    finally:
        store.remove(CallSid)

    return {"ok": True}
