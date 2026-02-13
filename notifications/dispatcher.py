"""Notification dispatcher — routes to all configured channels."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone

from config import get_settings
from store.conversations import CallSession
from notifications.telegram import send_call_summary as telegram_summary

logger = logging.getLogger("pdagent.notifications.dispatcher")

_file_lock = threading.Lock()


def _history_path() -> str:
    settings = get_settings()
    return os.path.join(settings.data_dir, "call_history.jsonl")


def _persist_call(session: CallSession, summary: str) -> None:
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


async def send_notifications(session: CallSession, summary: str) -> None:
    """Send notifications through all configured channels.

    Each channel is independent — one failing doesn't block the others.
    """
    # Persist to disk first (always — fast sync write with thread lock)
    try:
        _persist_call(session, summary)
    except Exception:
        logger.exception("Failed to persist call record")

    # Telegram notification
    try:
        await telegram_summary(session, summary)
    except Exception:
        logger.exception("Failed to send Telegram notification")
