"""WebSocket bridge between Twilio Media Streams and xAI Voice Agent."""

from __future__ import annotations

import asyncio
import json
import logging

from websockets.asyncio.client import connect as ws_connect

from config import get_settings
from store.conversations import CallSession
from agent.prompts import system_prompt

logger = logging.getLogger("pdagent.xai_bridge")

_XAI_REALTIME_URL = "wss://api.x.ai/v1/realtime"


class XAIVoiceBridge:
    """Bridges μ-law audio between a Twilio Media Stream and xAI Voice Agent."""

    def __init__(self, twilio_ws, session: CallSession, stream_sid: str):
        self._twilio = twilio_ws
        self._session = session
        self._stream_sid = stream_sid
        self._ending = False

    async def run(self) -> None:
        settings = get_settings()
        if not settings.xai_api_key:
            raise ValueError("XAI_API_KEY is required for the xAI voice bridge")

        url = f"{_XAI_REALTIME_URL}?model={settings.xai_voice_model}"
        headers = {"Authorization": f"Bearer {settings.xai_api_key}"}

        try:
            async with ws_connect(url, additional_headers=headers) as xai_ws:
                await self._configure_session(xai_ws)

                t2x = asyncio.create_task(self._twilio_to_xai(xai_ws))
                x2t = asyncio.create_task(self._xai_to_twilio(xai_ws))

                _, pending = await asyncio.wait(
                    [t2x, x2t], return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
        except Exception:
            logger.exception(f"Bridge error for call {self._session.call_sid}")

    async def _configure_session(self, xai_ws) -> None:
        settings = get_settings()

        # Replace text-sentinel ending instructions with function-call instruction
        base = system_prompt(settings.agent_name, settings.owner_name)
        if "## Ending the Call" in base:
            prompt = base.split("## Ending the Call")[0].rstrip()
        else:
            prompt = base
        prompt += (
            "\n\n## Ending the Call\n"
            "When the conversation is complete and you have said your goodbye, "
            "call the end_call function. Never mention the function to the caller."
        )

        location = ""
        if self._session.caller_city:
            location = f" from {self._session.caller_city}"
            if self._session.caller_state:
                location += f", {self._session.caller_state}"

        await xai_ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "voice": "rex",
                "instructions": prompt,
                "turn_detection": {"type": "server_vad"},
                "audio": {
                    "input": {"format": {"type": "audio/pcmu"}},
                    "output": {"format": {"type": "audio/pcmu"}},
                },
                "tools": [{
                    "type": "function",
                    "name": "end_call",
                    "description": "End the phone call after saying goodbye to the caller.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }],
            }
        }))

        # Trigger the opening greeting
        await xai_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": (
                        f"[SYSTEM: New call from {self._session.caller}{location}. "
                        "Greet the caller warmly and ask how you can help.]"
                    ),
                }],
            }
        }))
        await xai_ws.send(json.dumps({"type": "response.create"}))

    async def _twilio_to_xai(self, xai_ws) -> None:
        """Forward inbound Twilio audio to xAI (start event already consumed)."""
        try:
            async for raw in self._twilio.iter_text():
                data = json.loads(raw)
                if data.get("event") == "media":
                    await xai_ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": data["media"]["payload"],
                    }))
                elif data.get("event") == "stop":
                    logger.info(f"Twilio stop event for {self._session.call_sid}")
                    break
        except Exception:
            logger.debug(f"Twilio inbound stream ended for {self._session.call_sid}")

    async def _xai_to_twilio(self, xai_ws) -> None:
        """Forward xAI audio and events back to Twilio."""
        try:
            async for raw in xai_ws:
                event = json.loads(raw)
                etype = event.get("type")

                if etype == "response.output_audio.delta":
                    await self._twilio.send_text(json.dumps({
                        "event": "media",
                        "streamSid": self._stream_sid,
                        "media": {"payload": event["delta"]},
                    }))

                elif etype == "input_audio_buffer.speech_started":
                    # Caller interrupted — clear Twilio's outbound audio queue
                    await self._twilio.send_text(json.dumps({
                        "event": "clear",
                        "streamSid": self._stream_sid,
                    }))

                elif etype == "conversation.item.input_audio_transcription.completed":
                    text = event.get("transcript", "").strip()
                    if text:
                        self._session.add_caller_message(text)

                elif etype == "response.audio_transcript.done":
                    text = event.get("transcript", "").strip()
                    if text:
                        self._session.add_agent_message(text)

                elif etype == "response.function_call_arguments.done":
                    if event.get("name") == "end_call":
                        self._ending = True
                        # Acknowledge the function call and request a goodbye
                        await xai_ws.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": event["call_id"],
                                "output": "ok",
                            }
                        }))
                        await xai_ws.send(json.dumps({
                            "type": "response.create",
                            "response": {"instructions": "Say a warm, brief goodbye."},
                        }))

                elif etype == "response.done" and self._ending:
                    logger.info(f"Call complete via end_call for {self._session.call_sid}")
                    break

                elif etype == "error":
                    logger.error(f"xAI error event: {event}")

        except Exception:
            logger.debug(f"xAI stream ended for {self._session.call_sid}")
