"""Telegram Bot API notifications."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone
from html import escape

from config import get_settings
from store.conversations import CallSession

logger = logging.getLogger("pdagent.notifications.telegram")


def _send_telegram_sync(text: str) -> None:
    """Send an HTML message via Telegram Bot API (synchronous, for asyncio.to_thread)."""
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram not configured — skipping notification")
        return

    url = (
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    )
    payload = json.dumps({
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                logger.warning(f"Telegram API returned status {resp.status}")
    except urllib.error.URLError as exc:
        logger.error(f"Telegram send failed: {exc}")
        raise

    logger.info("Telegram notification sent successfully")


async def send_call_summary(session: CallSession, summary: str) -> None:
    """Send a formatted call summary via Telegram."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    location = f"{escape(session.caller_city or '?')}, {escape(session.caller_state or '?')}"
    text = (
        f"<b>Incoming Call Report</b>\n\n"
        f"<b>From:</b> {escape(session.caller)}\n"
        f"<b>Location:</b> {location}\n"
        f"<b>Duration:</b> {escape(session.duration_display)}\n"
        f"<b>Time:</b> {escape(timestamp)}\n\n"
        f"<pre>{escape(summary)}</pre>"
    )
    await asyncio.to_thread(_send_telegram_sync, text)


async def send_urgent_alert(session: CallSession, reason: str) -> None:
    """Send an urgent alert for calls that need immediate attention."""
    text = (
        f"\U0001f6a8 <b>URGENT — Immediate Attention Needed</b>\n\n"
        f"<b>From:</b> {escape(session.caller)}\n"
        f"<b>Reason:</b> {escape(reason)}\n\n"
        "The caller is still on the line or has just hung up. "
        "Please call back ASAP."
    )
    await asyncio.to_thread(_send_telegram_sync, text)
