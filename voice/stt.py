"""Optional server-side speech-to-text — Whisper fallback for browsers
without Web Speech API support."""

from __future__ import annotations

import asyncio
import logging
import tempfile

from fastapi import APIRouter, UploadFile, File, HTTPException

logger = logging.getLogger("pdagent.voice.stt")

router = APIRouter(prefix="/api/stt", tags=["stt"])

_whisper_model = None
MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25 MB


def _load_whisper():
    """Lazy-load Whisper model (only when first request arrives)."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    try:
        import whisper  # type: ignore[import-untyped]

        _whisper_model = whisper.load_model("base")
        logger.info("Whisper model loaded")
        return _whisper_model
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="openai-whisper is not installed. Use browser speech recognition.",
        )


def _transcribe_sync(audio_bytes: bytes) -> str:
    """Run Whisper transcription synchronously (called via to_thread)."""
    model = _load_whisper()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        result = model.transcribe(tmp.name, language="en")
    return result.get("text", "").strip()


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """Accept an audio file and return transcribed text."""
    # VULN-12: Read in chunks to avoid unbounded memory allocation
    chunks = []
    total = 0
    while True:
        chunk = await file.read(8192)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=413, detail="Audio file too large (max 25 MB)"
            )
        chunks.append(chunk)
    audio_bytes = b"".join(chunks)
    text = await asyncio.to_thread(_transcribe_sync, audio_bytes)
    return {"text": text}
