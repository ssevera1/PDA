"""Microsoft Graph calendar: free/busy reads and tentative holds.

Scott's mailbox and calendar are Exchange Online (GoDaddy-managed Microsoft
365 on scott@scottseverance.net), so the calendar backend is Graph, not
Google. Mirrors the auth pattern career-ops' scan-email.mjs already uses on
the same account: a public-client device-code flow (``scripts/ms_auth.py``,
one time), a refresh token stored at ``data/ms-token.json`` (gitignored), and
plain HTTPS calls — no SDK.

Delegated scopes: ``Calendars.ReadWrite offline_access``.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from config import get_settings
from agent.scheduling import Slot

logger = logging.getLogger("pdagent.mscal")

SCOPES = "https://graph.microsoft.com/Calendars.ReadWrite offline_access"
GRAPH = "https://graph.microsoft.com/v1.0"
CAL_TZ = "America/Chicago"


# ---------------------------------------------------------------------------
# Auth (device-code token minted by scripts/ms_auth.py; refreshed here)
# ---------------------------------------------------------------------------

def _load_token() -> dict:
    settings = get_settings()
    path = settings.ms_token_path
    if not os.path.exists(path):
        raise RuntimeError(f"No Microsoft token at {path} — run scripts/ms_auth.py once to sign in.")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _save_token(tok: dict) -> None:
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.ms_token_path) or ".", exist_ok=True)
    with open(settings.ms_token_path, "w", encoding="utf-8") as fh:
        json.dump(tok, fh)


def _post_form(url: str, form: dict) -> dict:
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _access_token() -> str:
    """Refresh-token exchange on every use; Graph access tokens are short-lived."""
    settings = get_settings()
    tok = _load_token()
    data = _post_form(
        f"https://login.microsoftonline.com/{settings.ms_tenant_id}/oauth2/v2.0/token",
        {
            "client_id": settings.ms_client_id,
            "grant_type": "refresh_token",
            "refresh_token": tok["refresh_token"],
            "scope": SCOPES,
        },
    )
    if "access_token" not in data:
        raise RuntimeError(f"Microsoft token refresh failed: {str(data)[:200]}")
    _save_token({
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", tok["refresh_token"]),
    })
    return data["access_token"]


def _graph_get(path: str, token: str) -> dict:
    req = urllib.request.Request(
        f"{GRAPH}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _graph_post(path: str, token: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{GRAPH}{path}",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


# ---------------------------------------------------------------------------
# Pure helpers (tested directly)
# ---------------------------------------------------------------------------

def _parse_graph_dt(node: dict) -> datetime:
    """Graph {'dateTime': '2026-09-01T15:00:00.0000000', 'timeZone': 'UTC'} -> aware dt.

    calendarView returns UTC unless a Prefer header says otherwise; we never
    send one, so treat anything labeled UTC (or unlabeled) as UTC.
    """
    raw = node.get("dateTime", "")
    if "." in raw:  # trim 7-digit fractional seconds Python can't parse
        head, frac = raw.split(".", 1)
        raw = f"{head}.{frac[:6]}"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        tz_name = (node.get("timeZone") or "UTC").upper()
        if tz_name in ("UTC", "Z"):
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            from zoneinfo import ZoneInfo

            dt = dt.replace(tzinfo=ZoneInfo(node.get("timeZone")))
    return dt


def parse_busy_graph(events: list[dict]) -> list[tuple[datetime, datetime]]:
    """calendarView events -> busy intervals; 'free' events don't block."""
    busy = []
    for ev in events:
        if ev.get("showAs", "busy") == "free" or ev.get("isCancelled"):
            continue
        try:
            busy.append((_parse_graph_dt(ev["start"]), _parse_graph_dt(ev["end"])))
        except (KeyError, ValueError):
            logger.warning(f"unparseable event skipped: {str(ev)[:120]}")
    return busy


def build_hold_event_graph(slot: Slot, *, name: str, company: str, phone: str, email: str, topic: str) -> dict:
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
        "subject": f"HOLD: {company or name or 'recruiter'} call",
        "body": {"contentType": "text", "content": "\n".join(lines)},
        "start": {"dateTime": slot.start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": CAL_TZ},
        "end": {"dateTime": slot.end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": CAL_TZ},
        "showAs": "tentative",
        "isReminderOn": True,
    }


# ---------------------------------------------------------------------------
# Entry points (same shape as integrations/gcal.py)
# ---------------------------------------------------------------------------

def fetch_busy(*, days: int, now: datetime | None = None, token: str | None = None) -> list[tuple[datetime, datetime]]:
    tok = token or _access_token()
    start = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    end = start + timedelta(days=days)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    path = (
        "/me/calendarView?startDateTime=" + start.strftime(fmt)
        + "&endDateTime=" + end.strftime(fmt)
        + "&$select=start,end,showAs,isCancelled&$top=100"
    )
    events: list[dict] = []
    while path:
        page = _graph_get(path, tok)
        events.extend(page.get("value", []))
        nxt = page.get("@odata.nextLink", "")
        path = nxt.replace(GRAPH, "") if nxt else ""
    return parse_busy_graph(events)


def create_hold(slot: Slot, *, name: str, company: str, phone: str, email: str, topic: str, token: str | None = None) -> str:
    tok = token or _access_token()
    body = build_hold_event_graph(slot, name=name, company=company, phone=phone, email=email, topic=topic)
    created = _graph_post("/me/events", tok, body)
    logger.info(f"Tentative hold created: {created.get('id', '')[:20]} {slot.start.isoformat()}")
    return created.get("webLink", "")
