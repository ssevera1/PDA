"""WebSocket-based voice call handler — replaces Twilio telephony."""

from __future__ import annotations

import logging
import re
import time
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config import get_settings
from store.conversations import store
from agent.brain import respond, generate_greeting, summarize_call
from notifications.dispatcher import send_notifications

logger = logging.getLogger("pdagent.voice")

router = APIRouter(tags=["voice"])

MAX_TURNS = 20
MAX_CONCURRENT_CALLS = 10
MAX_MESSAGE_LENGTH = 2000
MIN_MESSAGE_INTERVAL = 1.5  # seconds between speech messages


def _sanitize_field(value: str | None, max_len: int = 100) -> str | None:
    """Sanitize user-supplied fields: strip, truncate, remove newlines."""
    if value is None:
        return None
    value = str(value)[:max_len].strip()
    value = re.sub(r"[\r\n]", " ", value)
    return value or None


async def _send_json(ws: WebSocket, msg: dict) -> None:
    try:
        await ws.send_json(msg)
    except Exception:
        logger.debug("Failed to send WebSocket message (client may have disconnected)")


@router.websocket("/ws/call")
async def websocket_call(ws: WebSocket):
    """Handle a full voice call over WebSocket.

    Protocol (JSON messages with ``type`` field):
      Client -> Server: call_start, speech, call_end
      Server -> Client: greeting, agent_reply, call_ended, turn_limit, error
    """
    # VULN-05: Enforce concurrent connection limit
    if store.active_count() >= MAX_CONCURRENT_CALLS:
        await ws.close(code=4008, reason="Server busy")
        return

    # VULN-01: Validate WebSocket origin
    origin = (ws.headers.get("origin") or "").rstrip("/")
    if origin:
        settings = get_settings()
        allowed_origin = settings.base_url.rstrip("/")
        allowed_host = urlparse(allowed_origin).hostname
        request_host = urlparse(origin).hostname
        # Allow same-host connections (covers http/https, port variations)
        if request_host and allowed_host and request_host != allowed_host:
            # Also allow localhost for development
            if request_host not in ("localhost", "127.0.0.1"):
                await ws.close(code=4003, reason="Origin not allowed")
                return

    await ws.accept()
    session = None
    last_msg_time = 0.0

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            # ---- call_start ----
            if msg_type == "call_start":
                call_sid = f"WS_{uuid.uuid4().hex[:12]}"
                # VULN-11: Sanitize caller-controlled fields
                caller = _sanitize_field(
                    data.get("caller", "web-caller"), max_len=100
                ) or "web-caller"
                session = store.create(
                    call_sid=call_sid,
                    caller=caller,
                    caller_city=_sanitize_field(data.get("caller_city"), max_len=100),
                    caller_state=_sanitize_field(data.get("caller_state"), max_len=50),
                )
                greeting = await generate_greeting(session)
                spoken = greeting.replace("CALL_COMPLETE", "").strip()
                await _send_json(ws, {
                    "type": "greeting",
                    "text": spoken,
                    "call_sid": call_sid,
                })

            # ---- speech ----
            elif msg_type == "speech":
                if session is None:
                    await _send_json(ws, {
                        "type": "error",
                        "text": "Call not started. Send call_start first.",
                    })
                    continue

                # VULN-03: Per-message rate limiting
                now = time.time()
                if now - last_msg_time < MIN_MESSAGE_INTERVAL:
                    await _send_json(ws, {
                        "type": "error",
                        "text": "Please slow down.",
                    })
                    continue
                last_msg_time = now

                caller_said = (data.get("text") or "").strip()
                if not caller_said:
                    continue

                # VULN-04: Enforce message length limit
                if len(caller_said) > MAX_MESSAGE_LENGTH:
                    await _send_json(ws, {
                        "type": "error",
                        "text": "Message too long.",
                    })
                    continue

                # Enforce turn limit
                turn_count = sum(1 for m in session.messages if m["role"] == "user")
                if turn_count >= MAX_TURNS:
                    await _send_json(ws, {
                        "type": "turn_limit",
                        "text": (
                            "I appreciate your patience. I've taken note of everything, "
                            "and I'll make sure to pass along a detailed message. "
                            "Thank you so much for calling. Goodbye!"
                        ),
                    })
                    break

                reply = await respond(session, caller_said)
                call_complete = "CALL_COMPLETE" in reply
                spoken = reply.replace("CALL_COMPLETE", "").strip()

                if call_complete:
                    await _send_json(ws, {
                        "type": "agent_reply",
                        "text": spoken,
                        "call_complete": True,
                    })
                    break
                else:
                    await _send_json(ws, {
                        "type": "agent_reply",
                        "text": spoken,
                        "call_complete": False,
                    })

            # ---- call_end ----
            elif msg_type == "call_end":
                break

            else:
                # VULN-06: Truncate reflected value
                safe_type = str(msg_type)[:50]
                await _send_json(ws, {
                    "type": "error",
                    "text": f"Unknown message type: {safe_type}",
                })

    except WebSocketDisconnect:
        logger.info(
            f"WebSocket disconnected for {session.call_sid if session else 'unknown'}"
        )
    except Exception:
        logger.exception("WebSocket error")
    finally:
        # Summarize and notify if there was a real conversation
        if session and len(session.messages) > 1:
            try:
                summary = await summarize_call(session)
                await send_notifications(session, summary)
                logger.info(f"Summary sent for call {session.call_sid}")
            except Exception:
                logger.exception(
                    f"Failed to send summary for call "
                    f"{session.call_sid if session else 'unknown'}"
                )

        if session:
            store.remove(session.call_sid)

        try:
            await _send_json(ws, {"type": "call_ended"})
        except Exception:
            pass
