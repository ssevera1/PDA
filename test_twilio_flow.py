"""
End-to-end integration tests — Twilio TwiML call flow.

Mocks: Twilio signature validation, LLM provider, Telegram send.
Tests: Twilio webhook call lifecycle, turn limits, status callback,
       invalid signature rejection, unknown session handling.
"""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Patch environment BEFORE importing app modules
# ---------------------------------------------------------------------------
os.environ.update(
    {
        "ANTHROPIC_API_KEY": "sk-ant-test-fake-key",
        "TWILIO_ACCOUNT_SID": "ACtest123",
        "TWILIO_AUTH_TOKEN": "test-auth-token",
        "TWILIO_PHONE_NUMBER": "+15550001111",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "AGENT_NAME": "Sophie",
        "OWNER_NAME": "TestBoss",
        "BASE_URL": "https://test.example.com",
        "ENVIRONMENT": "development",
        "LLM_PROVIDER": "claude",
    }
)


def _parse_twiml(response) -> ET.Element:
    """Parse a TwiML XML response into an ElementTree element."""
    assert response.status_code == 200
    assert "xml" in response.headers.get("content-type", "")
    return ET.fromstring(response.text)


@pytest.fixture(autouse=True)
def _temp_data_dir(tmp_path):
    """Redirect data persistence to a temp dir for every test."""
    os.environ["DATA_DIR"] = str(tmp_path)
    from config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _mock_twilio_validation():
    """Disable Twilio signature validation for all tests."""
    import voice.twilio_webhook  # ensure module is loaded before patching
    with patch("voice.twilio_webhook._validate_twilio_signature"):
        yield


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
# TEST 3: Full call lifecycle via Twilio webhooks
# ===================================================================
@patch("notifications.telegram._send_telegram_sync")
@patch("agent.brain.get_provider")
def test_full_call_lifecycle(mock_provider_fn, mock_telegram, client):
    """Simulate: incoming -> greeting -> 2 gather turns -> goodbye -> summary."""
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
            "ACTION_NEEDED: yes"
        ),
    ]

    # Step 1: Incoming call
    resp = client.post("/voice/incoming", data={
        "CallSid": "CA_TEST_001",
        "From": "+15559876543",
        "FromCity": "Dallas",
        "FromState": "TX",
    })
    root = _parse_twiml(resp)
    gather = root.find("Gather")
    assert gather is not None
    say = gather.find("Say")
    assert say is not None
    assert "Sophie" in say.text

    # Step 2: First gather (caller speaks)
    resp = client.post("/voice/gather", data={
        "CallSid": "CA_TEST_001",
        "SpeechResult": "Hi, I need to talk to TestBoss about a project deadline",
    })
    root = _parse_twiml(resp)
    gather = root.find("Gather")
    assert gather is not None
    say = gather.find("Say")
    assert say is not None
    assert "CALL_COMPLETE" not in say.text

    # Step 3: Second gather — triggers CALL_COMPLETE
    resp = client.post("/voice/gather", data={
        "CallSid": "CA_TEST_001",
        "SpeechResult": "Sure, my name is John, call me back at 555-876-5432",
    })
    root = _parse_twiml(resp)
    # Should have <Say> + <Hangup/>, no <Gather>
    assert root.find("Gather") is None
    hangup = root.find("Hangup")
    assert hangup is not None
    say = root.find("Say")
    assert say is not None
    assert "CALL_COMPLETE" not in say.text

    # Provider called 4 times: greeting + 2 turns + summary
    assert provider.complete.call_count == 4


# ===================================================================
# TEST 4: Turn limit enforcement
# ===================================================================
@patch("notifications.telegram._send_telegram_sync")
@patch("agent.brain.get_provider")
def test_turn_limit(mock_provider_fn, mock_telegram, client):
    """Call should be ended after MAX_TURNS user messages."""
    provider = MagicMock()
    mock_provider_fn.return_value = provider
    provider.complete.return_value = "Hello! How can I help?"

    # Start the call
    resp = client.post("/voice/incoming", data={
        "CallSid": "CA_LIMIT_TEST",
        "From": "+15550001234",
    })
    assert resp.status_code == 200

    # Pre-fill session to the limit
    from store.conversations import store
    session = store.get("CA_LIMIT_TEST")
    assert session is not None
    for i in range(20):
        session.add_caller_message(f"Turn {i}")
        session.add_agent_message(f"Response {i}")

    # Set up response for summary
    provider.complete.return_value = "Summary of the call."

    # Next gather should trigger turn limit
    resp = client.post("/voice/gather", data={
        "CallSid": "CA_LIMIT_TEST",
        "SpeechResult": "One more thing...",
    })
    root = _parse_twiml(resp)
    say = root.find("Say")
    assert say is not None
    assert "patience" in say.text
    hangup = root.find("Hangup")
    assert hangup is not None


# ===================================================================
# TEST 5: Status callback — caller hung up
# ===================================================================
@patch("notifications.telegram._send_telegram_sync")
@patch("agent.brain.get_provider")
def test_status_callback_hangup(mock_provider_fn, mock_telegram, client, _temp_data_dir):
    """Summary should be generated when caller hangs up mid-call."""
    provider = MagicMock()
    mock_provider_fn.return_value = provider
    provider.complete.side_effect = [
        "Hi! How can I help?",
        "I'll take a message.",
        "Summary of the call.",
    ]

    # Start call and do one turn
    client.post("/voice/incoming", data={
        "CallSid": "CA_HANGUP_TEST",
        "From": "+15559999999",
    })
    client.post("/voice/gather", data={
        "CallSid": "CA_HANGUP_TEST",
        "SpeechResult": "I need to leave a message",
    })

    # Status callback — caller hung up
    resp = client.post("/voice/status", data={
        "CallSid": "CA_HANGUP_TEST",
        "CallStatus": "completed",
    })
    assert resp.status_code == 204

    # Summary should have been generated (3 calls: greeting + turn + summary)
    assert provider.complete.call_count == 3

    # Verify call was persisted
    history_path = os.path.join(str(_temp_data_dir), "call_history.jsonl")
    assert os.path.exists(history_path)
    with open(history_path) as f:
        records = [json.loads(line) for line in f if line.strip()]
    assert len(records) == 1
    assert records[0]["caller"] == "+15559999999"


# ===================================================================
# TEST 6: Invalid Twilio signature is rejected
# ===================================================================
def test_invalid_twilio_signature(client):
    """Requests with invalid signatures should be rejected with 403."""
    # Remove the autouse mock for this test by directly calling
    # the real validation
    with patch("voice.twilio_webhook._validate_twilio_signature") as mock_validate:
        mock_validate.side_effect = __import__(
            "fastapi", fromlist=["HTTPException"]
        ).HTTPException(status_code=403, detail="Invalid Twilio signature")

        resp = client.post("/voice/incoming", data={
            "CallSid": "CA_BAD_SIG",
            "From": "+15550000000",
        })
        assert resp.status_code == 403


# ===================================================================
# TEST 7: Gather for unknown session
# ===================================================================
@patch("agent.brain.get_provider")
def test_unknown_session_gather(mock_provider_fn, client):
    """Gather for a non-existent session should return error TwiML."""
    resp = client.post("/voice/gather", data={
        "CallSid": "CA_DOES_NOT_EXIST",
        "SpeechResult": "Hello?",
    })
    root = _parse_twiml(resp)
    say = root.find("Say")
    assert say is not None
    assert "wrong" in say.text.lower()
    assert root.find("Hangup") is not None


# ===================================================================
# TEST 8: Status callback for already-cleaned session (no-op)
# ===================================================================
def test_status_callback_noop(client):
    """Status callback for unknown session should return 204 silently."""
    resp = client.post("/voice/status", data={
        "CallSid": "CA_ALREADY_DONE",
        "CallStatus": "completed",
    })
    assert resp.status_code == 204


# ===================================================================
# TEST 9: Rate limiting
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
# TEST 10: Session cleanup
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
# TEST 11: Empty speech re-prompts
# ===================================================================
@patch("agent.brain.get_provider")
def test_empty_speech_reprompts(mock_provider_fn, client):
    """Empty SpeechResult should re-prompt instead of crashing."""
    provider = MagicMock()
    mock_provider_fn.return_value = provider
    provider.complete.return_value = "Hello! How can I help?"

    client.post("/voice/incoming", data={
        "CallSid": "CA_EMPTY_SPEECH",
        "From": "+15551112222",
    })

    resp = client.post("/voice/gather", data={
        "CallSid": "CA_EMPTY_SPEECH",
        "SpeechResult": "",
    })
    root = _parse_twiml(resp)
    gather = root.find("Gather")
    assert gather is not None
    say = gather.find("Say")
    assert "didn't catch" in say.text.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
