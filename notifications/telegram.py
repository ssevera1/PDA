from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from config import get_settings
from store.conversations import CallSession

logger = logging.getLogger("pdagent.notifications")

TELEGRAM_API = "https://api.telegram.org"


async def send_call_summary(session: CallSession, summary: str) -> None:
    """Send a formatted call summary to the owner via Telegram."""
    settings = get_settings()

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    message = (
        f"📞 <b>Incoming Call Report</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>From:</b> {_escape_html(session.caller)}\n"
        f"<b>Location:</b> {_escape_html(session.caller_city or '?')}, "
        f"{_escape_html(session.caller_state or '?')}\n"
        f"<b>Duration:</b> {session.duration_display}\n"
        f"<b>Time:</b> {timestamp}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<pre>{_escape_html(summary)}</pre>"
    )

    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f"Telegram API error: {resp.status_code} — {resp.text}")
            resp.raise_for_status()

    logger.info(f"Call summary sent to Telegram chat {settings.telegram_chat_id}")


async def send_urgent_alert(session: CallSession, reason: str) -> None:
    """Send an urgent alert for calls that need immediate attention."""
    settings = get_settings()

    message = (
        f"🚨 <b>URGENT — Immediate Attention Needed</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>From:</b> {_escape_html(session.caller)}\n"
        f"<b>Reason:</b> {_escape_html(reason)}\n\n"
        f"The caller is still on the line or has just hung up.\n"
        f"Please call back ASAP."
    )

    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, timeout=10)
        resp.raise_for_status()


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
