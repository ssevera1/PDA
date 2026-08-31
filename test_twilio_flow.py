"""
End-to-end integration tests — Twilio Media Streams call flow.

Mocks: Twilio signature validation, LLM provider, Telegram send, xAI bridge.
Tests: /voice/incoming TwiML, signature rejection, /voice/media-stream
       handshake and error handling, /voice/status callback.
"""

import json
import logging
import os
from unittest.mock import patch, MagicMock, AsyncMock
from xml.etree import ElementTree as ET

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


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
        "XAI_API_KEY": "xai-test-fake-key",
        "AGENT_NAME": "Sophie",
        "OWNER_NAME": "TestBoss",
        "BASE_URL": "https://test.example.com",
        "ENVIRONMENT": "development",
        "LLM_PROVIDER": "claude",
    }
)

VOICE_LOGGER = "pdagent.voice"


def _ws_url(call_sid: str) -> str:
    """Connect URL carrying a freshly minted single-use stream token."""
    from voice import stream_tokens

    return f"/voice/media-stream?t={stream_tokens.mint(call_sid)}"


def _parse_twiml(response) -> ET.Element:
    """Parse a TwiML XML response into an ElementTree element."""
    assert response.status_code == 200
    assert "xml" in response.headers.get("content-type", "")
    return ET.fromstring(response.text)


def _errors(records) -> list[logging.LogRecord]:
    return [r for r in records if r.levelno >= logging.ERROR]


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
    """Accept every Twilio signature by default; tests opt out explicitly."""
    import voice.twilio_webhook  # ensure module is loaded before patching

    with patch("voice.twilio_webhook._verify_signature"):
        yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """The rate limiter is a process-wide singleton — don't leak hits."""
    from security import _limiter

    _limiter._hits.clear()
    yield
    _limiter._hits.clear()


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


@pytest.fixture
def mock_post_call():
    """Stub the post-call summary/notification hooks used by the finally block."""
    with patch("voice.twilio_webhook.summarize_call", new=AsyncMock(return_value="s")), \
         patch("voice.twilio_webhook.send_notifications", new=AsyncMock()):
        yield


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
# TEST 3: Incoming call opens a Media Stream and creates a session
# ===================================================================
def test_incoming_call_connects_stream(client):
    resp = client.post("/voice/incoming", data={
        "CallSid": "CA_TEST_001",
        "From": "+15559876543",
        "FromCity": "Dallas",
        "FromState": "TX",
    })
    root = _parse_twiml(resp)
    stream = root.find("Connect/Stream")
    assert stream is not None
    assert stream.get("url") == "wss://test.example.com/voice/media-stream"
    param = stream.find("Parameter")
    assert param is not None and param.get("name") == "t"
    assert len(param.get("value")) >= 20  # single-use stream token, via <Parameter> (Twilio drops query strings)

    from store.conversations import store

    session = store.get("CA_TEST_001")
    assert session is not None
    assert session.caller == "+15559876543"
    assert session.caller_city == "Dallas"


# ===================================================================
# TEST 4: Invalid Twilio signature on /incoming is rejected with 403
#
# Regression: the handler must not convert a rejected signature into a
# 200 OK TwiML response — forged requests have to stay visible as 4xx.
# ===================================================================
def test_invalid_signature_on_incoming_returns_403(client):
    with patch("voice.twilio_webhook._verify_signature") as mock_verify:
        mock_verify.side_effect = HTTPException(
            status_code=403, detail="Invalid Twilio signature"
        )

        resp = client.post("/voice/incoming", data={
            "CallSid": "CA_BAD_SIG",
            "From": "+15550000000",
        })

    assert resp.status_code == 403

    from store.conversations import store

    assert store.get("CA_BAD_SIG") is None


# ===================================================================
# TEST 5: A signature validator blowing up must also fail closed
# ===================================================================
def test_signature_validator_crash_returns_500(client):
    with patch("voice.twilio_webhook._verify_signature") as mock_verify:
        mock_verify.side_effect = RuntimeError("validator exploded")

        resp = client.post("/voice/incoming", data={
            "CallSid": "CA_CRASH_SIG",
            "From": "+15550000000",
        })

    assert resp.status_code == 500

    from store.conversations import store

    assert store.get("CA_CRASH_SIG") is None


# ===================================================================
# TEST 6: Invalid Twilio signature on /status is rejected with 403
# ===================================================================
def test_invalid_signature_on_status_returns_403(client):
    with patch("voice.twilio_webhook._verify_signature") as mock_verify:
        mock_verify.side_effect = HTTPException(
            status_code=403, detail="Invalid Twilio signature"
        )

        resp = client.post("/voice/status", data={
            "CallSid": "CA_BAD_SIG",
            "CallStatus": "completed",
        })

    assert resp.status_code == 403


# ===================================================================
# TEST 7: Missing CallSid returns error TwiML, no session
# ===================================================================
def test_incoming_without_call_sid(client):
    resp = client.post("/voice/incoming", data={"From": "+15550000000"})
    root = _parse_twiml(resp)
    assert root.find("Hangup") is not None
    say = root.find("Say")
    assert say is not None and "error" in say.text.lower()

    from store.conversations import store

    assert store.active_count() == 0


# ===================================================================
# TEST 8: Concurrency cap returns the busy message
# ===================================================================
def test_max_concurrent_calls(client):
    from store.conversations import store
    from voice.twilio_webhook import MAX_CONCURRENT_CALLS

    for i in range(MAX_CONCURRENT_CALLS):
        store.create(call_sid=f"CA_BUSY_{i}", caller="+15550000000")

    resp = client.post("/voice/incoming", data={
        "CallSid": "CA_OVERFLOW",
        "From": "+15551234567",
    })
    root = _parse_twiml(resp)
    say = root.find("Say")
    assert say is not None and "busy" in say.text.lower()
    assert root.find("Hangup") is not None
    assert store.get("CA_OVERFLOW") is None


# ===================================================================
# TEST 9: Media stream handshake starts the bridge
# ===================================================================
def test_media_stream_starts_bridge(client, mock_post_call):
    from store.conversations import store

    store.create(call_sid="CA_WS_OK", caller="+15550001234")

    bridge_instance = MagicMock()
    bridge_instance.run = AsyncMock()

    with patch("voice.twilio_webhook.XAIVoiceBridge", return_value=bridge_instance) as mock_cls:
        with client.websocket_connect(_ws_url("CA_WS_OK")) as ws:
            ws.send_text(json.dumps({"event": "connected"}))
            ws.send_text(json.dumps({
                "event": "start",
                "start": {"callSid": "CA_WS_OK", "streamSid": "MZ_1"},
            }))

    bridge_instance.run.assert_awaited_once()
    assert mock_cls.call_args.kwargs["stream_sid"] == "MZ_1"
    # finally block cleans the session up
    assert store.get("CA_WS_OK") is None


# ===================================================================
# TEST 10: A caller hangup is a warning, not an error with a traceback
#
# Regression: WebSocketDisconnect is not a subclass of
# fastapi.exceptions.WebSocketException, so catching the latter let every
# hangup fall through to `except Exception` and log an ERROR + traceback.
# ===================================================================
def test_media_stream_disconnect_is_warning(client, mock_post_call, caplog):
    from store.conversations import store

    store.create(call_sid="CA_WS_BYE", caller="+15550001234")

    bridge_instance = MagicMock()
    bridge_instance.run = AsyncMock(side_effect=WebSocketDisconnect(code=1000))

    with caplog.at_level(logging.DEBUG, logger=VOICE_LOGGER):
        with patch("voice.twilio_webhook.XAIVoiceBridge", return_value=bridge_instance):
            with client.websocket_connect(_ws_url("CA_WS_BYE")) as ws:
                ws.send_text(json.dumps({"event": "connected"}))
                ws.send_text(json.dumps({
                    "event": "start",
                    "start": {"callSid": "CA_WS_BYE", "streamSid": "MZ_2"},
                }))

    voice_records = [r for r in caplog.records if r.name == VOICE_LOGGER]
    assert not _errors(voice_records), [r.getMessage() for r in _errors(voice_records)]
    assert any(
        r.levelno == logging.WARNING and "disconnected" in r.getMessage()
        for r in voice_records
    )
    assert store.get("CA_WS_BYE") is None


# ===================================================================
# TEST 11: Malformed frames warn without a traceback and don't abort
#
# Regression: garbage frames used to be logged at ERROR with exc_info=True,
# so a client spraying junk emitted unbounded full tracebacks.
# ===================================================================
def test_media_stream_malformed_frame_warns(client, mock_post_call, caplog):
    from store.conversations import store

    store.create(call_sid="CA_WS_JUNK", caller="+15550001234")

    bridge_instance = MagicMock()
    bridge_instance.run = AsyncMock()

    with caplog.at_level(logging.DEBUG, logger=VOICE_LOGGER):
        with patch("voice.twilio_webhook.XAIVoiceBridge", return_value=bridge_instance):
            with client.websocket_connect(_ws_url("CA_WS_JUNK")) as ws:
                ws.send_text("}{ not json at all")
                ws.send_text(json.dumps({
                    "event": "start",
                    "start": {"callSid": "CA_WS_JUNK", "streamSid": "MZ_3"},
                }))

    voice_records = [r for r in caplog.records if r.name == VOICE_LOGGER]
    assert not _errors(voice_records), [r.getMessage() for r in _errors(voice_records)]
    junk = [r for r in voice_records if "Malformed JSON" in r.getMessage()]
    assert len(junk) == 1
    assert junk[0].levelno == logging.WARNING
    assert junk[0].exc_info is None
    # The garbage frame did not abort the handshake
    bridge_instance.run.assert_awaited_once()


# ===================================================================
# TEST 12: A valid-JSON non-object frame is skipped, not a crash
# ===================================================================
def test_media_stream_non_object_frame(client, mock_post_call, caplog):
    from store.conversations import store

    store.create(call_sid="CA_WS_SCALAR", caller="+15550001234")

    bridge_instance = MagicMock()
    bridge_instance.run = AsyncMock()

    with caplog.at_level(logging.DEBUG, logger=VOICE_LOGGER):
        with patch("voice.twilio_webhook.XAIVoiceBridge", return_value=bridge_instance):
            with client.websocket_connect(_ws_url("CA_WS_SCALAR")) as ws:
                ws.send_text(json.dumps(123))
                ws.send_text(json.dumps({
                    "event": "start",
                    "start": {"callSid": "CA_WS_SCALAR", "streamSid": "MZ_4"},
                }))

    voice_records = [r for r in caplog.records if r.name == VOICE_LOGGER]
    assert not _errors(voice_records), [r.getMessage() for r in _errors(voice_records)]
    assert any("Non-object frame" in r.getMessage() for r in voice_records)
    bridge_instance.run.assert_awaited_once()


# ===================================================================
# TEST 13: Media stream for an unknown session closes without a bridge
# ===================================================================
def test_media_stream_unknown_session(client, mock_post_call):
    with patch("voice.twilio_webhook.XAIVoiceBridge") as mock_cls:
        with client.websocket_connect(_ws_url("CA_NOPE")) as ws:
            ws.send_text(json.dumps({
                "event": "start",
                "start": {"callSid": "CA_NOPE", "streamSid": "MZ_5"},
            }))

    mock_cls.assert_not_called()


# ===================================================================
# TEST 14: Status callback — caller hung up, summary is generated
# ===================================================================
@patch("notifications.telegram._send_telegram_sync")
@patch("agent.brain.get_provider")
def test_status_callback_hangup(mock_provider_fn, mock_telegram, client, _temp_data_dir):
    provider = MagicMock()
    mock_provider_fn.return_value = provider
    provider.complete.return_value = "Summary of the call."

    client.post("/voice/incoming", data={
        "CallSid": "CA_HANGUP_TEST",
        "From": "+15559999999",
    })

    from store.conversations import store

    session = store.get("CA_HANGUP_TEST")
    assert session is not None
    session.add_caller_message("I need to leave a message")
    session.add_agent_message("Sure, I'll take one.")

    resp = client.post("/voice/status", data={
        "CallSid": "CA_HANGUP_TEST",
        "CallStatus": "completed",
    })
    assert resp.status_code == 204
    assert provider.complete.call_count == 1
    assert store.get("CA_HANGUP_TEST") is None

    history_path = os.path.join(str(_temp_data_dir), "call_history.jsonl")
    assert os.path.exists(history_path)
    with open(history_path) as f:
        records = [json.loads(line) for line in f if line.strip()]
    assert len(records) == 1
    assert records[0]["caller"] == "+15559999999"


# ===================================================================
# TEST 15: Status callback for already-cleaned session (no-op)
# ===================================================================
def test_status_callback_noop(client):
    resp = client.post("/voice/status", data={
        "CallSid": "CA_ALREADY_DONE",
        "CallStatus": "completed",
    })
    assert resp.status_code == 204


# ===================================================================
# TEST 16: Status callback without a CallSid is a no-op 204
# ===================================================================
def test_status_callback_without_call_sid(client):
    resp = client.post("/voice/status", data={"CallStatus": "completed"})
    assert resp.status_code == 204


# ===================================================================
# TEST 17: Rate limiting
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
# TEST 18: Session cleanup
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


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
