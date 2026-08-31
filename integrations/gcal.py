"""Google Calendar: free/busy reads and tentative holds.

Network access is confined to this module and injectable for tests. The slot
math lives in ``agent/scheduling.py``; this file only fetches busy intervals
and writes the hold event. One-time consent is ``scripts/google_auth.py``,
which stores an authorized-user token at ``data/google-token.json``
(gitignored; the repo is public).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from config import get_settings
from agent.scheduling import Slot

logger = logging.getLogger("pdagent.gcal")

SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events",
]


def _service():
    """Build the Calendar API client from the stored token. Import lazily so
    tests (which inject a fake) never need the Google libraries loaded."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleRequest
    from googleapiclient.discovery import build

    settings = get_settings()
    token_path = settings.google_token_path
    if not os.path.exists(token_path):
        raise RuntimeError(
            f"No Google token at {token_path} — run scripts/google_auth.py once to authorize."
        )
    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        with open(token_path, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def parse_busy(response: dict, calendar_id: str) -> list[tuple[datetime, datetime]]:
    """freebusy response -> aware (start, end) tuples. Pure."""
    intervals = []
    calendars = response.get("calendars", {})
    for entry in calendars.get(calendar_id, {}).get("busy", []):
        start = datetime.fromisoformat(entry["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(entry["end"].replace("Z", "+00:00"))
        intervals.append((start, end))
    return intervals


def build_hold_event(slot: Slot, *, name: str, company: str, phone: str, email: str, topic: str) -> dict:
    """The exact payload written to the calendar. Pure, so tests pin it."""
    lines = [
        "Tentative hold created by Sophie (PDAgent) during a recruiter call.",
        f"Recruiter: {name or 'unknown'}",
        f"Company: {company or 'unknown'}",
        f"Phone: {phone or 'not given'}",
        f"Email: {email or 'not given'}",
        f"Topic: {topic or 'recruiter call'}",
        "",
        "Keep this event to confirm, or delete it to decline — deleting is the cancel button.",
    ]
    return {
        "summary": f"HOLD: {company or name or 'recruiter'} call",
        "description": "\n".join(lines),
        "start": {"dateTime": slot.start.isoformat()},
        "end": {"dateTime": slot.end.isoformat()},
        "status": "tentative",
        "reminders": {"useDefault": True},
    }


def fetch_busy(*, days: int, now: datetime | None = None, service=None) -> list[tuple[datetime, datetime]]:
    settings = get_settings()
    svc = service or _service()
    start = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    body = {
        "timeMin": start.isoformat(),
        "timeMax": (start + timedelta(days=days)).isoformat(),
        "items": [{"id": settings.google_calendar_id}],
    }
    response = svc.freebusy().query(body=body).execute()
    return parse_busy(response, settings.google_calendar_id)


def create_hold(slot: Slot, *, name: str, company: str, phone: str, email: str, topic: str, service=None) -> str:
    settings = get_settings()
    svc = service or _service()
    event = build_hold_event(slot, name=name, company=company, phone=phone, email=email, topic=topic)
    created = svc.events().insert(calendarId=settings.google_calendar_id, body=event).execute()
    link = created.get("htmlLink", "")
    logger.info(f"Tentative hold created: {created.get('id')} {slot.start.isoformat()}")
    return link
