"""In-call tools: schemas the xAI session declares, and the dispatcher that
executes them when the model calls one.

Contract with the bridge: ``dispatch`` NEVER raises. A tool failure returns a
JSON error string the model can speak around ("let me just take your
availability instead"); the call must survive every tool problem.
``end_call`` is intentionally absent here — the bridge owns the hangup
sequence itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from config import get_settings
from store.conversations import CallSession
from agent.scheduling import SchedulingRules, propose_slots

logger = logging.getLogger("pdagent.tools")

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "end_call",
        "description": "End the phone call after saying goodbye to the caller.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "get_availability",
        "description": (
            "Check the owner's real calendar and get up to three open interview slots. "
            "Only times returned by this tool may ever be offered to the caller."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "How many days out to search (default 7).",
                }
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "book_tentative",
        "description": (
            "Place a tentative hold on one of the slots get_availability returned. "
            "Requires the caller's name and company, plus a phone number or email."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_iso": {"type": "string", "description": "The start_iso of a slot from get_availability."},
                "name": {"type": "string"},
                "company": {"type": "string"},
                "phone": {"type": "string"},
                "email": {"type": "string"},
                "topic": {"type": "string", "description": "Role or subject of the call."},
            },
            "required": ["start_iso", "name"],
        },
    },
    {
        "type": "function",
        "name": "notify_owner",
        "description": (
            "Send the owner a live text notification while the call is still going. Use for "
            "anything urgent or unusually promising. The caller must never be told about it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "urgency": {"type": "string", "enum": ["info", "high"]},
                "text": {"type": "string"},
            },
            "required": ["text"],
        },
    },
    {
        "type": "function",
        "name": "lookup_opportunity",
        "description": (
            "Check whether a company or recruiter already has an opportunity in progress "
            "with the owner (his applications and Indeed messages)."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Company or recruiter name."}},
            "required": ["query"],
        },
    },
]


def _rules() -> SchedulingRules:
    settings = get_settings()
    return SchedulingRules(include_evenings=settings.scheduling_include_evenings)


async def _get_availability(args: dict, session: CallSession) -> str:
    settings = get_settings()
    if not settings.scheduling_enabled:
        return json.dumps({"error": "scheduling is not available; collect the caller's availability instead"})
    from integrations import calendar_api

    days = min(int(args.get("days_ahead") or 7), 14)
    rules = _rules()
    busy = await asyncio.to_thread(calendar_api.fetch_busy, days=max(days, rules.horizon_days))
    slots = propose_slots(busy, now=datetime.now(timezone.utc), rules=rules)
    if not slots:
        return json.dumps({"slots": [], "note": "no open slots; collect the caller's availability instead"})
    session.proposed_slots = {s.start.isoformat(): s.spoken() for s in slots}
    return json.dumps({
        "slots": [{"start_iso": s.start.isoformat(), "spoken": s.spoken()} for s in slots],
        "note": "offer only these times, by their spoken form",
    })


async def _book_tentative(args: dict, session: CallSession) -> str:
    settings = get_settings()
    if not settings.scheduling_enabled:
        return json.dumps({"error": "scheduling is not available"})
    start_iso = str(args.get("start_iso") or "")
    if start_iso not in session.proposed_slots:
        return json.dumps({
            "error": "that time was not offered by get_availability; call get_availability and offer one of its slots"
        })
    if not (args.get("phone") or args.get("email")):
        return json.dumps({"error": "need a phone number or email before booking; ask the caller for one"})

    from integrations import calendar_api
    from agent.scheduling import Slot
    from datetime import timedelta

    start = datetime.fromisoformat(start_iso)
    slot = Slot(start=start, end=start + timedelta(minutes=_rules().slot_minutes))
    link = await asyncio.to_thread(
        calendar_api.create_hold,
        slot,
        name=str(args.get("name") or ""),
        company=str(args.get("company") or ""),
        phone=str(args.get("phone") or ""),
        email=str(args.get("email") or ""),
        topic=str(args.get("topic") or ""),
    )
    session.slot_held = start_iso
    spoken = session.proposed_slots[start_iso]

    from notifications.telegram import send_live

    await send_live(
        f"\U0001f4c5 Sophie tentatively held {spoken} for "
        f"{args.get('name') or 'a recruiter'}"
        f"{' (' + str(args.get('company')) + ')' if args.get('company') else ''}. "
        f"Keep the calendar event to confirm, delete it to decline.\n{link}"
    )
    return json.dumps({
        "held": spoken,
        "note": "tell the caller the time is tentatively held and the owner will confirm by email",
    })


async def _notify_owner(args: dict, session: CallSession) -> str:
    prefix = "\U0001f6a8 " if args.get("urgency") == "high" else "\U0001f4de "
    from notifications.telegram import send_live

    await send_live(f"{prefix}Live call from {session.caller}: {str(args.get('text') or '')[:500]}")
    return json.dumps({"ok": True, "note": "owner notified; do not mention this to the caller"})


async def _lookup_opportunity(args: dict, session: CallSession) -> str:
    from integrations.careerops import lookup_opportunity

    line = await asyncio.to_thread(lookup_opportunity, str(args.get("query") or ""))
    if line:
        return json.dumps({"found": True, "status": line})
    return json.dumps({"found": False, "note": "no existing record; treat as a fresh opportunity"})


_HANDLERS = {
    "get_availability": _get_availability,
    "book_tentative": _book_tentative,
    "notify_owner": _notify_owner,
    "lookup_opportunity": _lookup_opportunity,
}


async def dispatch(name: str, args: dict, session: CallSession) -> str:
    """Execute one tool call. Always returns a JSON string; never raises."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        return await handler(args or {}, session)
    except Exception:
        logger.exception(f"tool {name} failed for call {session.call_sid}")
        return json.dumps({"error": f"{name} is unavailable right now; continue without it"})
