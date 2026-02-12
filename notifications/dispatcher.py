"""Notification dispatcher — routes to all configured channels."""

from __future__ import annotations

import logging

from store.conversations import CallSession
from notifications.email import send_call_summary as email_summary
from notifications.dashboard import broadcast_call_event, persist_call

logger = logging.getLogger("pdagent.notifications.dispatcher")


async def send_notifications(session: CallSession, summary: str) -> None:
    """Send notifications through all configured channels.

    Each channel is independent — one failing doesn't block the others.
    """
    # Persist to disk first (always — fast sync write with thread lock)
    try:
        persist_call(session, summary)
    except Exception:
        logger.exception("Failed to persist call record")

    # Email notification
    try:
        await email_summary(session, summary)
    except Exception:
        logger.exception("Failed to send email notification")

    # Dashboard SSE broadcast
    try:
        await broadcast_call_event(session, summary)
    except Exception:
        logger.exception("Failed to broadcast dashboard event")
