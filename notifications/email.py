"""SMTP email notifications — replaces Telegram notifications."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from config import get_settings
from store.conversations import CallSession

logger = logging.getLogger("pdagent.notifications.email")


def _build_summary_html(session: CallSession, summary: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""\
<html><body style="font-family:sans-serif;color:#333">
<h2>Incoming Call Report</h2>
<table style="border-collapse:collapse">
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">From:</td>
      <td>{escape(session.caller)}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Location:</td>
      <td>{escape(session.caller_city or "?")}, {escape(session.caller_state or "?")}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Duration:</td>
      <td>{escape(session.duration_display)}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:bold">Time:</td>
      <td>{escape(timestamp)}</td></tr>
</table>
<hr>
<pre style="white-space:pre-wrap">{escape(summary)}</pre>
</body></html>"""


def _build_urgent_html(session: CallSession, reason: str) -> str:
    return f"""\
<html><body style="font-family:sans-serif;color:#333">
<h2 style="color:#c00">URGENT &mdash; Immediate Attention Needed</h2>
<p><b>From:</b> {escape(session.caller)}</p>
<p><b>Reason:</b> {escape(reason)}</p>
<p>The caller is still on the line or has just hung up. Please call back ASAP.</p>
</body></html>"""


def _send_smtp(subject: str, html_body: str) -> None:
    """Synchronous SMTP send — run via asyncio.to_thread."""
    settings = get_settings()
    if not settings.smtp_host or not settings.notification_email:
        logger.warning("SMTP not configured — skipping email notification")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = settings.notification_email
    msg.attach(MIMEText(html_body, "html"))

    # VULN-24: Always use TLS with certificate verification
    tls_context = ssl.create_default_context()

    if settings.smtp_port == 465:
        # Implicit TLS (SMTPS)
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port,
            timeout=15, context=tls_context,
        ) as server:
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(
                msg["From"], [settings.notification_email], msg.as_string()
            )
    else:
        # STARTTLS (port 587 or others) — always upgrade to TLS
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls(context=tls_context)
            server.ehlo()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(
                msg["From"], [settings.notification_email], msg.as_string()
            )

    # VULN-15: Don't log PII
    logger.info("Email notification sent successfully")


async def send_call_summary(session: CallSession, summary: str) -> None:
    """Send a formatted call summary via email."""
    html = _build_summary_html(session, summary)
    subject = f"Call Report — {session.caller}"
    await asyncio.to_thread(_send_smtp, subject, html)


async def send_urgent_alert(session: CallSession, reason: str) -> None:
    """Send an urgent alert for calls that need immediate attention."""
    html = _build_urgent_html(session, reason)
    subject = f"URGENT — Call from {session.caller}"
    await asyncio.to_thread(_send_smtp, subject, html)
