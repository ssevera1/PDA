"""SSE dashboard endpoint and call history persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from config import get_settings
from security import require_api_key
from store.conversations import CallSession

logger = logging.getLogger("pdagent.notifications.dashboard")

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# In-memory set of SSE subscriber queues
_subscribers: list[asyncio.Queue] = []
MAX_SSE_SUBSCRIBERS = 20
MAX_HISTORY_RECORDS = 500
_file_lock = threading.Lock()


def _history_path() -> str:
    settings = get_settings()
    return os.path.join(settings.data_dir, "call_history.jsonl")


def persist_call(session: CallSession, summary: str) -> None:
    """Append a call record to the JSONL history file."""
    record = {
        "call_sid": str(session.call_sid)[:50],
        "caller": str(session.caller)[:200],
        "caller_city": str(session.caller_city or "")[:100] or None,
        "caller_state": str(session.caller_state or "")[:50] or None,
        "started_at": session.started_at,
        "duration_seconds": int(session.duration_seconds),
        "duration_display": session.duration_display,
        "summary": str(summary)[:5000],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "turn_count": sum(1 for m in session.messages if m["role"] == "user"),
    }
    path = _history_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _file_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    logger.info(f"Persisted call record for {session.call_sid}")


async def broadcast_call_event(session: CallSession, summary: str) -> None:
    """Push a new-call event to all SSE subscribers."""
    event_data = {
        "type": "new_call",
        "call_sid": session.call_sid,
        "caller": session.caller,
        "caller_city": session.caller_city,
        "caller_state": session.caller_state,
        "duration_display": session.duration_display,
        "summary": summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload = json.dumps(event_data)
    dead: list[asyncio.Queue] = []
    # VULN-31: Iterate over a snapshot
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        if q in _subscribers:
            _subscribers.remove(q)


@router.get("/events")
async def sse_events(request: Request, api_key: str = Depends(require_api_key)):
    """Server-Sent Events stream for real-time call notifications."""
    # VULN-22: Cap subscriber count
    if len(_subscribers) >= MAX_SSE_SUBSCRIBERS:
        raise HTTPException(status_code=503, detail="Too many dashboard connections")

    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers.append(q)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if q in _subscribers:
                _subscribers.remove(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history")
async def get_history(
    api_key: str = Depends(require_api_key),
    limit: int = Query(default=100, le=MAX_HISTORY_RECORDS, ge=1),
    offset: int = Query(default=0, ge=0),
):
    """Return past call records from the JSONL file with pagination (VULN-18)."""
    path = _history_path()
    if not os.path.exists(path):
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < offset:
                continue
            if len(records) >= limit:
                break
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records
