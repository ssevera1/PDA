"""Optional server-side text-to-speech — pyttsx3 fallback for browsers
without SpeechSynthesis API support."""

from __future__ import annotations

import asyncio
import io
import logging
import tempfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("pdagent.voice.tts")

router = APIRouter(prefix="/api/tts", tags=["tts"])


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


def _synthesize_sync(text: str) -> bytes:
    """Run pyttsx3 synthesis synchronously (called via to_thread)."""
    try:
        import pyttsx3  # type: ignore[import-untyped]
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="pyttsx3 is not installed. Use browser speech synthesis.",
        )

    engine = pyttsx3.init()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        engine.save_to_file(text, tmp.name)
        engine.runAndWait()
        tmp.seek(0)
        return tmp.read()


@router.post("/speak")
async def speak(req: SpeakRequest):
    """Accept text and return synthesized WAV audio."""
    audio = await asyncio.to_thread(_synthesize_sync, req.text)
    return Response(content=audio, media_type="audio/wav")
