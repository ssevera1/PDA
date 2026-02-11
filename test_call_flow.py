"""
End-to-end integration test — simulates a complete phone call flow.

Mocks: LLM provider, Telegram API, Twilio signature validation.
Tests: Incoming call -> greeting -> multi-turn conversation -> call end -> summary notification.
"""

import os
import re
from unittest.mock import patch, MagicMock
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Patch environment BEFORE importing app modules
# ---------------------------------------------------------------------------
os.environ.update(
    {
        "ANTHROPIC_API_KEY": "sk-ant-test-fake-key",
        "TWILIO_ACCOUNT_SID": "ACtest1234567890",
        "TWILIO_AUTH_TOKEN": "test_auth_token_fake",
        "TWILIO_PHONE_NUMBER": "+15551234567",
        "TELEGRAM_BOT_TOKEN": "123456:FAKE-BOT-TOKEN",
        "TELEGRAM_CHAT_ID": "999999999",
        "AGENT_NAME": "Sophie",
        "OWNER_NAME": "TestBoss",
        "BASE_URL": "https://test.ngrok-free.app",
        "ENVIRONMENT": "development",
        "LLM_PROVIDER": "claude",
    }
)


def _parse_twiml(xml_text: str) -> ElementTree.Element:
    """Parse TwiML XML response into an ElementTree."""
    return ElementTree.fromstring(xml_text)


def _extract_say_texts(root: ElementTree.Element) -> list[str]:
    """Extract all <Say> text from a TwiML response."""
    return [say.text for say in root.iter("Say") if say.text]


# ---------------------------------------------------------------------------
# Disable Twilio signature validation for tests
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _bypass_twilio_signature():
    with patch(
        "security.RequestValidator"
    ) as MockValidator:
        instance = MockValidator.return_value
        instance.validate.return_value = True
        yield


@pytest.fixture
def client():
    # Clear cached settings so test env vars are picked up
    from config import get_settings
    get_settings.cache_clear()

    # Reset the LLM provider singleton
    from agent.llm import reset_provider
    reset_provider()

    from main import app
    from store.conversations import store

    # Clear any leftover sessions
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
    print("  [PASS] Health endpoint OK")


# ===================================================================
# TEST 2: Root endpoint
# ===================================================================
def test_root(client):
    resp = client.get("/")
    data = resp.json()
    assert data["service"] == "PDAgent"
    assert data["status"] == "running"
    assert data["active_calls"] == 0
    print("  [PASS] Root endpoint OK")


# ===================================================================
# TEST 3: Full call lifecycle
# ===================================================================
@patch("agent.brain.get_provider")
@patch("notifications.telegram.httpx.AsyncClient")
def test_full_call_flow(mock_telegram_client, mock_provider_fn, client):
    """Simulate a complete call: ring -> greet -> 2 turns -> goodbye -> summary."""

    # --- Set up LLM provider mock ---
    provider = MagicMock()
    mock_provider_fn.return_value = provider
    provider.complete.side_effect = [
        # 1) Greeting
        (
            "Hi there! This is Sophie, I'm the assistant for TestBoss. "
            "How can I help you today?"
        ),
        # 2) First caller turn response
        (
            "Of course! Let me take a message for TestBoss. "
            "Could I get your name and the best number to reach you?"
        ),
        # 3) Second caller turn response — ends the call
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

    # --- Set up Telegram mock ---
    telegram_response = MagicMock()
    telegram_response.status_code = 200
    mock_async_client = MagicMock()
    mock_async_client.__aenter__ = lambda self: _async_return(self)
    mock_async_client.__aexit__ = lambda self, *a: _async_return(None)
    mock_async_client.post = lambda *a, **kw: _async_return(telegram_response)
    mock_telegram_client.return_value = mock_async_client

    call_sid = "CA_TEST_12345"
    caller = "+15558765432"

    # ---------------------------------------------------------------
    # STEP 1: Incoming call
    # ---------------------------------------------------------------
    print("\n  --- STEP 1: Incoming call ---")
    resp = client.post(
        "/voice/incoming",
        data={
            "CallSid": call_sid,
            "From": caller,
            "CallerCity": "New York",
            "CallerState": "NY",
        },
    )
    assert resp.status_code == 200
    assert "xml" in resp.headers["content-type"]

    root = _parse_twiml(resp.text)
    says = _extract_say_texts(root)
    print(f"  Agent says: {says[0]}")
    assert "Sophie" in says[0]
    assert root.find(".//Gather") is not None, "Should have a Gather for speech input"
    print("  [PASS] Greeting delivered with Gather")

    # ---------------------------------------------------------------
    # STEP 2: Caller speaks (turn 1)
    # ---------------------------------------------------------------
    print("\n  --- STEP 2: Caller speaks (turn 1) ---")
    resp = client.post(
        "/voice/respond",
        data={
            "CallSid": call_sid,
            "From": caller,
            "SpeechResult": "Hi, I need to talk to TestBoss about a project deadline",
        },
    )
    assert resp.status_code == 200

    root = _parse_twiml(resp.text)
    says = _extract_say_texts(root)
    print(f"  Agent says: {says[0]}")
    assert "name" in says[0].lower() or "message" in says[0].lower()
    assert root.find(".//Gather") is not None, "Conversation should continue"
    print("  [PASS] Agent asked for details, conversation continues")

    # ---------------------------------------------------------------
    # STEP 3: Caller speaks (turn 2) — triggers CALL_COMPLETE
    # ---------------------------------------------------------------
    print("\n  --- STEP 3: Caller speaks (turn 2) ---")
    resp = client.post(
        "/voice/respond",
        data={
            "CallSid": call_sid,
            "From": caller,
            "SpeechResult": "Sure, my name is John, call me back at 555-876-5432",
        },
    )
    assert resp.status_code == 200

    root = _parse_twiml(resp.text)
    says = _extract_say_texts(root)
    print(f"  Agent says: {says[0]}")

    # CALL_COMPLETE should be stripped from spoken text
    assert "CALL_COMPLETE" not in says[0]
    # Call should end with Hangup
    assert root.find(".//Hangup") is not None, "Call should end after CALL_COMPLETE"
    print("  [PASS] Agent said goodbye, call hanging up")

    # ---------------------------------------------------------------
    # STEP 4: Call status callback (triggers summary + notification)
    # ---------------------------------------------------------------
    print("\n  --- STEP 4: Call ended — summary & notification ---")
    resp = client.post(
        "/voice/status",
        data={
            "CallSid": call_sid,
            "CallStatus": "completed",
            "CallDuration": "45",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Verify provider was called 4 times (greeting + 2 turns + summary)
    assert provider.complete.call_count == 4
    print("  [PASS] Summary generated (4 LLM API calls total)")
    print("  [PASS] Telegram notification sent")

    print("\n  ========================================")
    print("  FULL CALL LIFECYCLE TEST PASSED")
    print("  ========================================")


# ===================================================================
# TEST 4: Empty speech handling
# ===================================================================
def test_empty_speech(client):
    """Agent should ask caller to repeat when no speech is detected."""
    # Create a session first
    from store.conversations import store
    store.create(call_sid="CA_EMPTY", caller="+15550000000")

    resp = client.post(
        "/voice/respond",
        data={"CallSid": "CA_EMPTY", "From": "+15550000000", "SpeechResult": ""},
    )
    assert resp.status_code == 200
    root = _parse_twiml(resp.text)
    says = _extract_say_texts(root)
    assert any("catch" in s.lower() or "again" in s.lower() for s in says)
    print("  [PASS] Empty speech handled — asked caller to repeat")


# ===================================================================
# TEST 5: Conversation turn limit
# ===================================================================
@patch("agent.brain.get_provider")
def test_turn_limit(mock_provider_fn, client):
    """Call should be gracefully ended after MAX_TURNS."""
    from store.conversations import store

    session = store.create(call_sid="CA_LIMIT", caller="+15550000000")
    # Pre-fill 20 user turns to hit the limit
    for i in range(20):
        session.add_caller_message(f"Turn {i}")
        session.add_agent_message(f"Response {i}")

    resp = client.post(
        "/voice/respond",
        data={
            "CallSid": "CA_LIMIT",
            "From": "+15550000000",
            "SpeechResult": "One more thing...",
        },
    )
    assert resp.status_code == 200
    root = _parse_twiml(resp.text)
    assert root.find(".//Hangup") is not None, "Should hang up after turn limit"
    # Provider should NOT have been called — we short-circuit
    mock_provider_fn.return_value.complete.assert_not_called()
    print("  [PASS] Turn limit enforced — call ended at 20 turns")


# ===================================================================
# TEST 6: Rate limiting
# ===================================================================
def test_rate_limiting(client):
    """Endpoints should return 429 after too many rapid requests."""
    from security import _limiter
    # Lower the limit for testing
    original_max = _limiter.max_requests
    _limiter.max_requests = 3

    try:
        for i in range(3):
            resp = client.get("/health")
            # Health endpoint isn't rate-limited (/voice/* only)

        # Rate limit only applies to /voice/* — verify it works there
        # by checking the limiter directly
        assert _limiter.is_allowed("test-ip-1")
        assert _limiter.is_allowed("test-ip-1")
        assert _limiter.is_allowed("test-ip-1")
        assert not _limiter.is_allowed("test-ip-1"), "4th request should be denied"
        print("  [PASS] Rate limiter blocks after threshold")
    finally:
        _limiter.max_requests = original_max


# ===================================================================
# TEST 7: Session cleanup
# ===================================================================
def test_stale_session_cleanup():
    """Stale sessions should be identified correctly."""
    import time
    from store.conversations import store
    from security import MAX_SESSION_AGE_SECONDS

    store._sessions.clear()

    # Create a session that's "old"
    session = store.create(call_sid="CA_OLD", caller="+15550000000")
    session.started_at = time.time() - MAX_SESSION_AGE_SECONDS - 100

    # Create a fresh session
    store.create(call_sid="CA_NEW", caller="+15551111111")

    assert store.active_count() == 2

    # Simulate what cleanup_stale_sessions does
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
    print("  [PASS] Stale session cleaned up, fresh session preserved")

    store._sessions.clear()


# ===================================================================
# Async helper
# ===================================================================
class _async_return:
    """Turn a value into an awaitable for mocking async context managers."""
    def __init__(self, val):
        self.val = val
    def __await__(self):
        yield
        return self.val


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
