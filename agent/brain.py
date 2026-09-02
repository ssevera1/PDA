"""Post-call intelligence. The live conversation happens inside the xAI voice
session; this module only runs after (or as) a call ends: one Claude pass that
produces a structured extract plus the human-readable Telegram report.

The v2 turn-by-turn webhook path (``respond`` / ``generate_greeting``) is gone
with the architecture that needed it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from store.conversations import CallSession
from agent.prompts import EXTRACT_PROMPT
from agent.llm import get_provider

logger = logging.getLogger("pdagent.brain")

_REPORT_FIELDS = [
    ("caller_type", "Type"),
    ("caller_name", "Caller"),
    ("company", "Company"),
    ("role", "Role"),
    ("comp_range", "Comp"),
    ("location_policy", "Location"),
    ("callback_phone", "Callback"),
    ("email", "Email"),
    ("timeline", "Timeline"),
    ("slot_held", "Slot held"),
    ("urgency", "Urgency"),
    ("action_needed", "Action"),
]


def parse_extract(raw: str) -> dict | None:
    """The model's JSON, tolerantly parsed. None when it isn't JSON at all."""
    text = raw.strip()
    text = re.sub(r"^```[a-z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def render_report(extract: dict) -> str:
    """The Telegram-facing report for a parsed extract."""
    lines = []
    for key, label in _REPORT_FIELDS:
        value = extract.get(key)
        if value in (None, "", []):
            continue
        lines.append(f"{label}: {value}")
    flags = extract.get("red_flags") or []
    if flags:
        lines.append("Red flags: " + "; ".join(str(f) for f in flags))
    summary = extract.get("summary")
    if summary:
        lines.append("")
        lines.append(str(summary))
    return "\n".join(lines) if lines else "No details extracted."


async def summarize_call(session: CallSession) -> str:
    """Structured extract + report. Sets ``session.extract`` when parseable."""
    if not session.messages:
        session.summary = "No conversation captured."
        return session.summary

    transcript = "\n\n".join(
        f"{'Caller' if m['role'] == 'user' else 'Agent'}: {m['content']}" for m in session.messages
    )
    if session.slot_held:
        transcript += f"\n\n[SYSTEM: a tentative hold was booked for {session.slot_held}]"

    raw = await asyncio.to_thread(
        get_provider().complete,
        system=EXTRACT_PROMPT,
        messages=[{"role": "user", "content": f"Here is the call transcript:\n\n{transcript}"}],
        max_tokens=1000,
    )
    extract = parse_extract(raw)
    if extract is not None:
        if session.slot_held and not extract.get("slot_held"):
            extract["slot_held"] = session.slot_held
        session.extract = extract
        session.summary = render_report(extract)
    else:
        logger.warning(f"extract was not valid JSON for {session.call_sid}; using raw text")
        session.summary = raw.strip()[:4000]
    return session.summary
