"""
End-to-end integration tests — WebSocket-based call flow.

Mocks: LLM provider, SMTP email, JSONL persistence (temp dir).
Tests: WebSocket call lifecycle, turn limits, disconnect cleanup,
       dashboard auth, and dashboard history.
"""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Patch environment BEFORE importing app modules
# ---------------------------------------------------------------------------
os.environ.update(
    {
        "ANTHROPIC_API_KEY": "sk-ant-test-fake-key",
        "TWILIO_ACCOUNT_SID": "",
        "TWILIO_AUTH_TOKEN": "",
        "TWILIO_PHONE_NUMBER": "",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "SMTP_HOST": "",
        "NOTIFICATION_EMAIL": "",
        "DASHBOARD_API_KEY": "test-secret-key",
        "AGENT_NAME": "Sophie",
        "OWNER_NAME": "TestBoss",
        "BASE_URL": "https://test.example.com",
        "ENVIRONMENT": "development",
        "LLM_PROVIDER": "claude",
    }
)


@pytest.fixture(autouse=True)
def _temp_data_dir(tmp_path):
    """Redirect data persistence to a temp dir for every test."""
    os.environ["DATA_DIR"] = str(tmp_path)
    from config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _disable_ws_rate_limit():
    """Disable per-message rate limiting in WebSocket handler for tests."""
    import voice.websocket as ws_mod

    original = ws_mod.MIN_MESSAGE_INTERVAL
    ws_mod.MIN_MESSAGE_INTERVAL = 0
    yield
    ws_mod.MIN_MESSAGE_INTERVAL = original


@pytest.fixture
def client():
    from config import get_settings

    get_settings.cache_clear()

    from agent.llm import reset_provider

    reset_provider()

    from main import app
    from store.conversations import store

    store._sessions.clear()

    with TestClient(app) as c:
        yield c

    store._sessions.clear()
    reset_provider()


# ===================================================================
# TEST 1: Health check
# ===================================================================
def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


# ===================================================================
# TEST 2: Root endpoint
# ===================================================================
def test_root(client):
    resp = client.get("/")
    data = resp.json()
    assert data["service"] == "PDAgent"
    assert data["status"] == "running"


# ===================================================================
# TEST 3: Full call lifecycle via WebSocket
# ===================================================================
@patch("notifications.email._send_smtp")
@patch("agent.brain.get_provider")
def test_full_call_lifecycle_ws(mock_provider_fn, mock_smtp, client):
    """Simulate: connect -> greeting -> 2 turns -> goodbye -> summary."""
    provider = MagicMock()
    mock_provider_fn.return_value = provider
    provider.complete.side_effect = [
        # 1) Greeting
        (
            "Hi there! This is Sophie, I'm the assistant for TestBoss. "
            "How can I help you today?"
        ),
        # 2) First caller turn
        (
            "Of course! Let me take a message for TestBoss. "
            "Could I get your name and the best number to reach you?"
        ),
        # 3) Second caller turn — ends the call
        (
            "Got it, John. I'll make sure TestBoss gets your message "
            "about the project deadline. He'll call you back at "
            "five five five, eight seven six, five four three two. "
            "Thanks for calling! CALL_COMPLETE"
        ),
        # 4) Post-call summary
        (
            "CALLER: John\n"
            "CALLBACK: 555-876-5432\n"
            "TOPIC: Project deadline question\n"
            "DETAILS:\n"
            "- Caller asked about project deadline\n"
            "- Wants TestBoss to call back regarding timeline\n"
            "- Left callback number\n"
            "ACTION_NEEDED: yes\n"
            "ACTION: Call John back about project deadline\n"
            "URGENCY: medium\n"
            "RESOLUTION: Message taken, not fully resolved"
        ),
    ]

    with client.websocket_connect("/ws/call") as ws:
        # Start call
        ws.send_json({"type": "call_start", "caller": "web-test-caller"})
        msg = ws.receive_json()
        assert msg["type"] == "greeting"
        assert "Sophie" in msg["text"]
        assert "call_sid" in msg

        # Turn 1
        ws.send_json(
            {
                "type": "speech",
                "text": "Hi, I need to talk to TestBoss about a project deadline",
            }
        )
        msg = ws.receive_json()
        assert msg["type"] == "agent_reply"
        assert msg["call_complete"] is False

        # Turn 2 — triggers CALL_COMPLETE
        ws.send_json(
            {
                "type": "speech",
                "text": "Sure, my name is John, call me back at 555-876-5432",
            }
        )
        msg = ws.receive_json()
        assert msg["type"] == "agent_reply"
        assert msg["call_complete"] is True
        assert "CALL_COMPLETE" not in msg["text"]

    # Provider called 4 times: greeting + 2 turns + summary
    assert provider.complete.call_count == 4


# ===================================================================
# TEST 4: Turn limit enforcement via WebSocket
# ===================================================================
@patch("notifications.email._send_smtp")
@patch("agent.brain.get_provider")
def test_turn_limit_ws(mock_provider_fn, mock_smtp, client):
    """Call should be ended after MAX_TURNS user messages."""
    provider = MagicMock()
    mock_provider_fn.return_value = provider
    # Greeting
    provider.complete.return_value = "Hello! How can I help?"

    with client.websocket_connect("/ws/call") as ws:
        ws.send_json({"type": "call_start", "caller": "limit-tester"})
        ws.receive_json()  # greeting

        # Set up responses for 20 turns
        provider.complete.side_effect = [f"Response {i}" for i in range(20)] + [
            "summary"
        ]

        from store.conversations import store

        # Get the session and pre-fill it to the limit
        sessions = list(store._sessions.values())
        assert len(sessions) == 1
        session = sessions[0]
        for i in range(20):
            session.add_caller_message(f"Turn {i}")
            session.add_agent_message(f"Response {i}")

        # Next speech should trigger turn limit
        ws.send_json({"type": "speech", "text": "One more thing..."})
        msg = ws.receive_json()
        assert msg["type"] == "turn_limit"


# ===================================================================
# TEST 5: Disconnect cleanup — summary generated
# ===================================================================
@patch("notifications.email._send_smtp")
@patch("agent.brain.get_provider")
def test_disconnect_cleanup(mock_provider_fn, mock_smtp, client, _temp_data_dir):
    """Summary should be generated when WebSocket drops mid-call."""
    provider = MagicMock()
    mock_provider_fn.return_value = provider
    provider.complete.side_effect = [
        "Hi! How can I help?",
        "I'll take a message.",
        "Summary of the call.",
    ]

    with client.websocket_connect("/ws/call") as ws:
        ws.send_json({"type": "call_start", "caller": "disconnect-tester"})
        ws.receive_json()  # greeting

        ws.send_json({"type": "speech", "text": "I need to leave a message"})
        ws.receive_json()  # agent_reply

    # After disconnect, summary should have been generated (3 calls total)
    assert provider.complete.call_count == 3

    # Verify call was persisted
    history_path = os.path.join(str(_temp_data_dir), "call_history.jsonl")
    assert os.path.exists(history_path)
    with open(history_path) as f:
        records = [json.loads(line) for line in f if line.strip()]
    assert len(records) == 1
    assert records[0]["caller"] == "disconnect-tester"


# ===================================================================
# TEST 6: Dashboard requires API key authentication
# ===================================================================
def test_dashboard_requires_auth(client):
    """Dashboard endpoints should return 401 without valid API key."""
    # No key
    resp = client.get("/api/dashboard/history")
    assert resp.status_code in (401, 422)

    # Wrong key
    resp = client.get(
        "/api/dashboard/history", headers={"X-API-Key": "wrong-key"}
    )
    assert resp.status_code == 401

    # Correct key
    resp = client.get(
        "/api/dashboard/history",
        headers={"X-API-Key": "test-secret-key"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ===================================================================
# TEST 7: Dashboard history shows records after call completion
# ===================================================================
@patch("notifications.email._send_smtp")
@patch("agent.brain.get_provider")
def test_dashboard_history(mock_provider_fn, mock_smtp, client):
    """Call records should appear in dashboard history after completion."""
    provider = MagicMock()
    mock_provider_fn.return_value = provider
    provider.complete.side_effect = [
        "Hello!",
        "Goodbye! CALL_COMPLETE",
        "CALLER: Test\nTOPIC: Quick question",
    ]

    with client.websocket_connect("/ws/call") as ws:
        ws.send_json({"type": "call_start", "caller": "history-tester"})
        ws.receive_json()

        ws.send_json({"type": "speech", "text": "Quick question"})
        ws.receive_json()

    # Check dashboard history
    resp = client.get(
        "/api/dashboard/history",
        headers={"X-API-Key": "test-secret-key"},
    )
    assert resp.status_code == 200
    records = resp.json()
    assert len(records) >= 1
    assert any(r["caller"] == "history-tester" for r in records)


# ===================================================================
# TEST 8: Rate limiting
# ===================================================================
def test_rate_limiting(client):
    """Rate limiter should block after threshold."""
    from security import _limiter

    original_max = _limiter.max_requests
    _limiter.max_requests = 3

    try:
        assert _limiter.is_allowed("test-ip-1")
        assert _limiter.is_allowed("test-ip-1")
        assert _limiter.is_allowed("test-ip-1")
        assert not _limiter.is_allowed("test-ip-1"), "4th request should be denied"
    finally:
        _limiter.max_requests = original_max


# ===================================================================
# TEST 9: Session cleanup
# ===================================================================
def test_stale_session_cleanup():
    """Stale sessions should be identified and removed."""
    import time
    from store.conversations import store
    from security import MAX_SESSION_AGE_SECONDS

    store._sessions.clear()

    session = store.create(call_sid="CA_OLD", caller="+15550000000")
    session.started_at = time.time() - MAX_SESSION_AGE_SECONDS - 100

    store.create(call_sid="CA_NEW", caller="+15551111111")

    assert store.active_count() == 2

    now = time.time()
    stale = [
        sid
        for sid, s in store._sessions.items()
        if (now - s.started_at) > MAX_SESSION_AGE_SECONDS
    ]
    for sid in stale:
        store.remove(sid)

    assert store.active_count() == 1
    assert store.get("CA_NEW") is not None
    assert store.get("CA_OLD") is None

    store._sessions.clear()


# ===================================================================
# TEST 10: Call and dashboard pages are served
# ===================================================================
def test_call_page(client):
    resp = client.get("/call")
    assert resp.status_code == 200
    assert "Call Sophie" in resp.text


def test_dashboard_page(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Dashboard" in resp.text


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
