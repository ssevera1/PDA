"""Unit tests for the pure cores of the Google Calendar and career-ops integrations."""

from datetime import datetime
from zoneinfo import ZoneInfo

from agent.scheduling import Slot
from integrations.gcal import build_hold_event, parse_busy
from integrations.mscal import build_hold_event_graph, parse_busy_graph
from integrations.careerops import parse_tracker_rows, search_records

CT = ZoneInfo("America/Chicago")
SLOT = Slot(
    start=datetime(2026, 9, 1, 14, 30, tzinfo=CT),
    end=datetime(2026, 9, 1, 15, 0, tzinfo=CT),
)


def test_parse_busy_reads_utc_intervals():
    response = {
        "calendars": {
            "primary": {
                "busy": [
                    {"start": "2026-09-01T15:00:00Z", "end": "2026-09-01T16:00:00Z"},
                ]
            }
        }
    }
    busy = parse_busy(response, "primary")
    assert len(busy) == 1
    start, end = busy[0]
    assert start.tzinfo is not None and end.tzinfo is not None
    assert start.astimezone(CT).hour == 10  # 15:00 UTC == 10:00 CDT


def test_parse_busy_handles_missing_calendar():
    assert parse_busy({}, "primary") == []


def test_hold_event_is_tentative_with_contact_details():
    event = build_hold_event(
        SLOT, name="Dana Fields", company="Meridian", phone="214-555-0147",
        email="m@meridian.com", topic="Platform AI role",
    )
    assert event["status"] == "tentative"
    assert event["summary"] == "HOLD: Meridian call"
    assert "Dana Fields" in event["description"]
    assert "delete it to decline" in event["description"]
    assert event["start"]["dateTime"].startswith("2026-09-01T14:30")


def test_hold_event_survives_missing_fields():
    event = build_hold_event(SLOT, name="", company="", phone="", email="", topic="")
    assert event["summary"] == "HOLD: recruiter call"
    assert "not given" in event["description"]


TRACKER = """\
| # | Date | Company | Role | Score | Status | PDF | Report | Notes |
|---|------|---------|------|-------|--------|-----|--------|-------|
| 366 | 2026-08-30 | Bluefin Systems | Senior Principal Engineer | N/A | Responded | X | - | Indeed |
| 375 | 2026-08-30 | Meridian Talent | Platform AI Engineer | N/A | Responded | X | - | Indeed |
"""

THREADS = [
    {"recruiter": "Riley Moon", "company": None, "replied": True},
    {"recruiter": "Casey Brooks", "company": None, "replied": False},
]


def test_tracker_rows_parse():
    rows = parse_tracker_rows(TRACKER)
    assert [r["company"] for r in rows] == ["Bluefin Systems", "Meridian Talent"]
    assert rows[0]["status"] == "Responded"


def test_company_lookup_matches_loosely():
    rows = parse_tracker_rows(TRACKER)
    line = search_records("Bluefin", rows, THREADS)
    assert line is not None and "Bluefin" in line and "Responded" in line
    line2 = search_records("meridian talent inc", rows, THREADS)
    assert line2 is not None and "Meridian" in line2


def test_recruiter_lookup_reports_reply_state():
    line = search_records("Riley", parse_tracker_rows(TRACKER), THREADS)
    assert line is not None and "replied" in line
    line2 = search_records("Brooks", parse_tracker_rows(TRACKER), THREADS)
    assert line2 is not None and "no reply" in line2


def test_short_or_unknown_queries_return_none():
    rows = parse_tracker_rows(TRACKER)
    assert search_records("ab", rows, THREADS) is None
    assert search_records("Globex Corporation", rows, THREADS) is None


# ---------------------------------------------------------------------------
# Microsoft Graph backend (the default: Exchange Online via GoDaddy M365)
# ---------------------------------------------------------------------------

def test_graph_busy_parses_utc_and_skips_free_and_cancelled():
    events = [
        {"start": {"dateTime": "2026-09-01T15:00:00.0000000", "timeZone": "UTC"},
         "end": {"dateTime": "2026-09-01T16:00:00.0000000", "timeZone": "UTC"},
         "showAs": "busy"},
        {"start": {"dateTime": "2026-09-01T17:00:00.0000000", "timeZone": "UTC"},
         "end": {"dateTime": "2026-09-01T18:00:00.0000000", "timeZone": "UTC"},
         "showAs": "free"},
        {"start": {"dateTime": "2026-09-01T19:00:00.0000000", "timeZone": "UTC"},
         "end": {"dateTime": "2026-09-01T20:00:00.0000000", "timeZone": "UTC"},
         "showAs": "busy", "isCancelled": True},
    ]
    busy = parse_busy_graph(events)
    assert len(busy) == 1
    start, end = busy[0]
    assert start.astimezone(CT).hour == 10  # 15:00 UTC == 10:00 CDT
    assert end.tzinfo is not None


def test_graph_busy_tolerates_garbage_events():
    assert parse_busy_graph([{"showAs": "busy"}, {}]) == []


def test_graph_hold_event_is_tentative_in_central_time():
    event = build_hold_event_graph(
        SLOT, name="Dana Fields", company="Meridian", phone="214-555-0147",
        email="m@meridian.com", topic="Platform AI role",
    )
    assert event["showAs"] == "tentative"
    assert event["subject"] == "HOLD: Meridian call"
    assert event["start"] == {"dateTime": "2026-09-01T14:30:00", "timeZone": "America/Chicago"}
    assert "delete it to decline" in event["body"]["content"]
    assert event["body"]["contentType"] == "text"
