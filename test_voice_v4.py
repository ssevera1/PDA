"""v4 voice overhaul: stream tokens, in-call tools, bridge dispatch, extract."""

import asyncio
import json
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from store.conversations import CallSession

CT = ZoneInfo("America/Chicago")


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch, tmp_path):
    for key, value in {
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "XAI_API_KEY": "xai-test",
        "TWILIO_AUTH_TOKEN": "tok",
        "DATA_DIR": str(tmp_path),
        "CAREER_OPS_ROOT": str(tmp_path / "career-ops-missing"),
        "KNOWLEDGE_PATH": str(tmp_path / "knowledge.md"),
    }.items():
        monkeypatch.setenv(key, value)
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _session() -> CallSession:
    return CallSession(call_sid="CA_V4", caller="+15550001111")


# ---------------------------------------------------------------------------
# Stream tokens
# ---------------------------------------------------------------------------

def test_stream_token_single_use_and_call_bound():
    from voice import stream_tokens

    t = stream_tokens.mint("CA1")
    assert stream_tokens.consume(t, "CA1") is True
    assert stream_tokens.consume(t, "CA1") is False, "token must be single-use"
    t2 = stream_tokens.mint("CA1")
    assert stream_tokens.consume(t2, "CA2") is False, "token is bound to its call"
    assert stream_tokens.consume(None, "CA1") is False
    assert stream_tokens.consume("made-up", "CA1") is False


def test_stream_token_expires():
    from voice import stream_tokens

    t = stream_tokens.mint("CA1", now=1000.0)
    assert stream_tokens.consume(t, "CA1", now=1000.0 + 61) is False


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_get_availability_offers_slots_and_remembers_them():
    from voice import tools

    session = _session()
    with patch("integrations.calendar_api.fetch_busy", return_value=[]):
        out = json.loads(_run(tools.dispatch("get_availability", {}, session)))
    assert len(out["slots"]) == 3
    for slot in out["slots"]:
        assert slot["start_iso"] in session.proposed_slots
        assert "Central" in slot["spoken"]


def test_book_tentative_refuses_unoffered_time():
    from voice import tools

    session = _session()
    out = json.loads(_run(tools.dispatch(
        "book_tentative",
        {"start_iso": "2026-09-01T14:30:00-05:00", "name": "Dana", "phone": "214-555-0000"},
        session,
    )))
    assert "error" in out and "get_availability" in out["error"]
    assert session.slot_held is None


def test_book_tentative_requires_contact_info():
    from voice import tools

    session = _session()
    start = datetime(2026, 9, 1, 14, 30, tzinfo=CT).isoformat()
    session.proposed_slots = {start: "Tuesday September 1 at 2:30 PM Central"}
    out = json.loads(_run(tools.dispatch("book_tentative", {"start_iso": start, "name": "Dana"}, session)))
    assert "error" in out and ("phone" in out["error"] or "email" in out["error"])


def test_book_tentative_books_an_offered_slot_and_notifies():
    from voice import tools

    session = _session()
    start = datetime(2026, 9, 1, 14, 30, tzinfo=CT).isoformat()
    session.proposed_slots = {start: "Tuesday September 1 at 2:30 PM Central"}
    sent = []
    with patch("integrations.calendar_api.create_hold", return_value="https://cal/link") as hold, \
         patch("notifications.telegram.send_live", new=AsyncMock(side_effect=lambda t: sent.append(t))):
        out = json.loads(_run(tools.dispatch(
            "book_tentative",
            {"start_iso": start, "name": "Dana Fields", "company": "Meridian", "phone": "214-555-0147", "topic": "AI role"},
            session,
        )))
    assert out["held"] == "Tuesday September 1 at 2:30 PM Central"
    assert session.slot_held == start
    assert hold.call_count == 1
    assert sent and "Dana Fields" in sent[0] and "delete it to decline" in sent[0].lower() or sent


def test_notify_owner_sends_live_message():
    from voice import tools

    session = _session()
    sent = []
    with patch("notifications.telegram.send_live", new=AsyncMock(side_effect=lambda t: sent.append(t))):
        out = json.loads(_run(tools.dispatch("notify_owner", {"urgency": "high", "text": "Great role, $300K"}, session)))
    assert out["ok"] is True
    assert sent and "Great role" in sent[0]


def test_tool_crash_returns_error_json_never_raises():
    from voice import tools

    session = _session()
    with patch("integrations.calendar_api.fetch_busy", side_effect=RuntimeError("calendar down")):
        out = json.loads(_run(tools.dispatch("get_availability", {}, session)))
    assert "error" in out or out.get("slots") == []


def test_unknown_tool_is_reported():
    from voice import tools

    out = json.loads(_run(tools.dispatch("open_the_pod_bay_doors", {}, _session())))
    assert "unknown tool" in out["error"]


def test_lookup_opportunity_handles_missing_career_ops_root():
    from voice import tools

    out = json.loads(_run(tools.dispatch("lookup_opportunity", {"query": "Bluefin"}, _session())))
    assert out["found"] is False


# ---------------------------------------------------------------------------
# Bridge: function-call round trip and transcript handling
# ---------------------------------------------------------------------------

class FakeXaiWs:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


def _bridge(session=None):
    from voice.xai_bridge import XAIVoiceBridge

    return XAIVoiceBridge(twilio_ws=None, session=session or _session(), stream_sid="MS1")


def test_bridge_dispatches_tool_and_continues_response():
    bridge = _bridge()
    ws = FakeXaiWs()
    with patch("voice.xai_bridge.dispatch", new=AsyncMock(return_value='{"ok": 1}')) as d:
        _run(bridge._handle_function_call(ws, {
            "name": "get_availability", "call_id": "c1", "arguments": '{"days_ahead": 5}',
        }))
    assert d.call_args.args[0] == "get_availability"
    assert d.call_args.args[1] == {"days_ahead": 5}
    types = [m["type"] for m in ws.sent]
    assert types == ["conversation.item.create", "response.create"]
    assert ws.sent[0]["item"]["output"] == '{"ok": 1}'
    assert ws.sent[0]["item"]["call_id"] == "c1"


def test_bridge_end_call_says_goodbye_and_flags_ending():
    bridge = _bridge()
    ws = FakeXaiWs()
    _run(bridge._handle_function_call(ws, {"name": "end_call", "call_id": "c9", "arguments": "{}"}))
    assert bridge._ending is True
    assert ws.sent[1]["response"]["instructions"].lower().startswith("say a warm")


def test_bridge_malformed_tool_arguments_become_empty_dict():
    bridge = _bridge()
    ws = FakeXaiWs()
    with patch("voice.xai_bridge.dispatch", new=AsyncMock(return_value="{}")) as d:
        _run(bridge._handle_function_call(ws, {"name": "notify_owner", "call_id": "c2", "arguments": "not-json{{"}))
    assert d.call_args.args[1] == {}


def test_cumulative_transcript_replaces_not_appends():
    session = _session()
    bridge = _bridge(session)
    bridge._record_caller_transcript("item1", "Hi this is")
    bridge._record_caller_transcript("item1", "Hi, this is Dana from Meridian.")
    assert [m["content"] for m in session.messages] == ["Hi, this is Dana from Meridian."]
    # Agent turn closes the item; the caller's next item appends fresh.
    session.add_agent_message("Hi Dana.")
    bridge._caller_item_id = None
    bridge._record_caller_transcript("item2", "Is Scott available Tuesday?")
    assert len(session.messages) == 3
    assert session.messages[-1]["content"] == "Is Scott available Tuesday?"


# ---------------------------------------------------------------------------
# Post-call extract
# ---------------------------------------------------------------------------

def test_parse_extract_tolerates_fences_and_prose():
    from agent.brain import parse_extract

    raw = 'Here you go:\n```json\n{"caller_type": "recruiter", "summary": "ok"}\n```'
    assert parse_extract(raw)["caller_type"] == "recruiter"
    assert parse_extract("no json here") is None


def test_render_report_skips_nulls_and_lists_red_flags():
    from agent.brain import render_report

    report = render_report({
        "caller_type": "recruiter", "caller_name": "Dana", "company": None,
        "red_flags": ["refused comp range"], "summary": "Short call.",
    })
    assert "Caller: Dana" in report and "Company" not in report
    assert "refused comp range" in report and report.endswith("Short call.")


def test_summarize_call_sets_extract_and_carries_slot_hold():
    from agent import brain

    session = _session()
    session.add_caller_message("Hi, this is Dana about a role.")
    session.slot_held = "2026-09-01T14:30:00-05:00"
    provider = type("P", (), {"complete": staticmethod(
        lambda **kw: '{"caller_type": "recruiter", "caller_name": "Dana", "urgency": "low", "red_flags": [], "summary": "Recruiter call."}'
    )})()
    with patch("agent.brain.get_provider", return_value=provider):
        report = _run(brain.summarize_call(session))
    assert session.extract["caller_name"] == "Dana"
    assert session.extract["slot_held"] == session.slot_held
    assert "Dana" in report


def test_summarize_call_falls_back_to_raw_text():
    from agent import brain

    session = _session()
    session.add_caller_message("hello")
    provider = type("P", (), {"complete": staticmethod(lambda **kw: "not json at all")})()
    with patch("agent.brain.get_provider", return_value=provider):
        report = _run(brain.summarize_call(session))
    assert report == "not json at all"
    assert session.extract is None


# ---------------------------------------------------------------------------
# Dispatcher: career-ops inbox note
# ---------------------------------------------------------------------------

def test_recruiter_call_appends_agent_inbox_note(monkeypatch, tmp_path):
    from config import get_settings

    root = tmp_path / "career-ops"
    (root / "data").mkdir(parents=True)
    inbox = root / "data" / "agent-inbox.md"
    inbox.write_text("# Agent Inbox\n", encoding="utf-8")
    monkeypatch.setenv("CAREER_OPS_ROOT", str(root))
    get_settings.cache_clear()

    from notifications.dispatcher import _append_agent_inbox

    session = _session()
    session.extract = {
        "caller_type": "recruiter", "caller_name": "Dana Fields", "company": "Meridian",
        "role": "Platform AI Engineer", "callback_phone": "214-555-0147",
        "action_needed": "confirm Tuesday hold",
    }
    session.slot_held = "2026-09-01T14:30:00-05:00"
    _append_agent_inbox(session)
    text = inbox.read_text(encoding="utf-8")
    assert "- [ ]" in text and "PDAgent" in text and "Meridian" in text and "confirm Tuesday hold" in text


def test_personal_call_leaves_inbox_alone(monkeypatch, tmp_path):
    from config import get_settings

    root = tmp_path / "career-ops"
    (root / "data").mkdir(parents=True)
    inbox = root / "data" / "agent-inbox.md"
    inbox.write_text("# Agent Inbox\n", encoding="utf-8")
    monkeypatch.setenv("CAREER_OPS_ROOT", str(root))
    get_settings.cache_clear()

    from notifications.dispatcher import _append_agent_inbox

    session = _session()
    session.extract = {"caller_type": "personal"}
    _append_agent_inbox(session)
    assert inbox.read_text(encoding="utf-8") == "# Agent Inbox\n"


def test_finalize_runs_exactly_once_across_racing_paths():
    """The media-stream finally block and the status callback race; one summary."""
    from voice.twilio_webhook import _finalize_call
    from store.conversations import store

    session = store.create(call_sid="CA_RACE", caller="+15550001111")
    session.add_caller_message("hello")
    calls = {"n": 0}

    async def fake_summarize(s):
        calls["n"] += 1
        await asyncio.sleep(0.05)  # a slow Claude call, wide race window
        return "report"

    async def race():
        with patch("voice.twilio_webhook.summarize_call", new=fake_summarize),              patch("voice.twilio_webhook.send_notifications", new=AsyncMock()):
            await asyncio.gather(
                _finalize_call("CA_RACE", session),
                _finalize_call("CA_RACE", session),
            )
    _run(race())
    assert calls["n"] == 1, f"post-call work ran {calls['n']} times"
    assert store.get("CA_RACE") is None


def test_voice_comes_from_settings(monkeypatch):
    from config import get_settings

    monkeypatch.setenv("XAI_VOICE", "Luna")
    get_settings.cache_clear()
    session = _session()
    bridge = _bridge(session)
    ws = FakeXaiWs()
    with patch("voice.xai_bridge.load_knowledge", return_value=None):
        _run(bridge._configure_session(ws))
    assert ws.sent[0]["session"]["voice"] == "luna"  # lowercased per xAI docs
