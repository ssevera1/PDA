"""Read-only lookups against the career-ops pipeline on this machine.

Sophie uses this mid-call to sound informed: "Scott replied to your Indeed
message yesterday." Strictly read-only — PDAgent never writes career-ops
files except the agent-inbox note the dispatcher appends after a call.
"""

from __future__ import annotations

import json
import logging
import os
import re

from config import get_settings

logger = logging.getLogger("pdagent.careerops")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def parse_tracker_rows(text: str) -> list[dict]:
    """applications.md table -> [{num, company, role, status}]. Pure."""
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 8 or not cells[1].isdigit():
            continue
        rows.append({"num": cells[1], "company": cells[3], "role": cells[4], "status": cells[6]})
    return rows


def search_records(query: str, rows: list[dict], threads: list[dict]) -> str | None:
    """Best one-line status for a company or recruiter name. Pure.

    Tracker rows win over Indeed threads; a two-way substring match on
    normalized names keeps 'Bluefin' matching 'Bluefin Systems, Inc.'.
    """
    q = _norm(query)
    if len(q) < 3:
        return None

    def hit(candidate: str) -> bool:
        c = _norm(candidate)
        return bool(c) and len(c) >= 3 and (q in c or c in q)

    for row in rows:
        if hit(row.get("company", "")):
            role = f" ({row['role']})" if row.get("role") and row["role"] not in ("?",) else ""
            return f"{row['company']}{role}: tracked in Scott's pipeline, status {row['status']}."

    for t in threads:
        if hit(t.get("recruiter", "")) or hit(t.get("company", "") or ""):
            who = t.get("recruiter") or t.get("company") or "that contact"
            if t.get("replied"):
                return f"{who}: Scott replied on Indeed recently."
            return f"{who}: has messaged Scott on Indeed; no reply has gone out yet."
    return None


def _load_threads(root: str) -> list[dict]:
    path = os.path.join(root, "data", "indeed-threads.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        parsed = json.load(fh)
    threads = parsed.get("threads", parsed if isinstance(parsed, list) else [])
    out = []
    for t in threads:
        out.append({
            "recruiter": t.get("recruiter", ""),
            "company": None,
            "replied": any(m.get("from") == "me" for m in t.get("messages", [])),
        })
    return out


def lookup_opportunity(query: str) -> str | None:
    """Entry point for the in-call tool. Never raises."""
    try:
        root = get_settings().career_ops_root
        if not root or not os.path.isdir(root):
            return None
        tracker = os.path.join(root, "data", "applications.md")
        rows = []
        if os.path.exists(tracker):
            with open(tracker, encoding="utf-8") as fh:
                rows = parse_tracker_rows(fh.read())
        return search_records(query, rows, _load_threads(root))
    except Exception:
        logger.exception("career-ops lookup failed")
        return None
