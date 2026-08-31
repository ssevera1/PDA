"""Unit tests for LLM timeout/retry configuration and event-loop safety.

Covers the guarantees the timeout+retry work is supposed to provide:
  * clients are built with a request timeout and a *bounded* retry budget
  * complete() never returns None — a failing request raises
  * provider calls do not block the event loop
"""

import asyncio
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

import agent.llm as llm
from store.conversations import CallSession


def _connection_error(exc_cls) -> Exception:
    return exc_cls(request=httpx.Request("POST", "https://example.invalid/v1"))


# ---------------------------------------------------------------------------
# Client configuration
# ---------------------------------------------------------------------------

def test_claude_client_gets_timeout_and_bounded_retries():
    with patch.object(llm.anthropic, "Anthropic") as ctor:
        llm.ClaudeProvider(api_key="sk-test")

    kwargs = ctor.call_args.kwargs
    assert kwargs["timeout"] == llm._TIMEOUT_SECONDS
    # Without this the SDK's own default (2 retries) multiplies with any
    # retry loop of ours: 3 x 3 = 9 network attempts per complete().
    assert kwargs["max_retries"] == llm._MAX_RETRIES


def test_openai_compatible_client_gets_timeout_and_bounded_retries():
    with patch.object(llm.openai, "OpenAI") as ctor:
        llm.GrokProvider(api_key="xai-test")

    kwargs = ctor.call_args.kwargs
    assert kwargs["timeout"] == llm._TIMEOUT_SECONDS
    assert kwargs["max_retries"] == llm._MAX_RETRIES


def test_total_attempts_stay_within_a_webhook_budget():
    """Worst case wall clock must stay in the same order as Twilio's timeouts."""
    attempts = llm._MAX_RETRIES + 1
    assert attempts <= 3
    assert attempts * llm._TIMEOUT_SECONDS <= 120


# ---------------------------------------------------------------------------
# complete() never falls through to None
# ---------------------------------------------------------------------------

def test_claude_complete_raises_on_connection_error():
    with patch.object(llm.anthropic, "Anthropic") as ctor:
        client = ctor.return_value
        client.messages.create.side_effect = _connection_error(
            llm.anthropic.APIConnectionError
        )
        provider = llm.ClaudeProvider(api_key="sk-test")

        with pytest.raises(llm.anthropic.APIConnectionError):
            provider.complete(system="s", messages=[{"role": "user", "content": "hi"}])

    # One call — retries belong to the SDK, not to a loop on top of it.
    assert client.messages.create.call_count == 1


def test_openai_complete_raises_on_connection_error():
    with patch.object(llm.openai, "OpenAI") as ctor:
        client = ctor.return_value
        client.chat.completions.create.side_effect = _connection_error(
            llm.openai.APIConnectionError
        )
        provider = llm.GeminiProvider(api_key="g-test")

        with pytest.raises(llm.openai.APIConnectionError):
            provider.complete(system="s", messages=[{"role": "user", "content": "hi"}])

    assert client.chat.completions.create.call_count == 1


@pytest.mark.parametrize("max_retries", [0, 1, 2])
def test_complete_never_returns_none_for_any_retry_budget(monkeypatch, max_retries):
    """Regression: a retry loop whose exhausted path has no explicit raise
    returns None once the budget is reconfigured, and that None only blows up
    by callers of the provider."""
    monkeypatch.setattr(llm, "_MAX_RETRIES", max_retries)

    with patch.object(llm.anthropic, "Anthropic") as ctor:
        ctor.return_value.messages.create.side_effect = _connection_error(
            llm.anthropic.APIConnectionError
        )
        provider = llm.ClaudeProvider(api_key="sk-test")

        result = None
        with pytest.raises(llm.anthropic.APIConnectionError):
            result = provider.complete(system="s", messages=[])
        assert result is None  # never assigned; the call raised


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_claude_complete_returns_text():
    with patch.object(llm.anthropic, "Anthropic") as ctor:
        thinking = MagicMock()
        thinking.type = "thinking"  # Opus 5 thinks adaptively; text extraction must skip this
        block = MagicMock()
        block.type = "text"
        block.text = "hello"
        ctor.return_value.messages.create.return_value.content = [thinking, block]
        provider = llm.ClaudeProvider(api_key="sk-test")

        assert provider.complete(system="s", messages=[]) == "hello"


def test_openai_complete_returns_empty_string_for_null_content():
    with patch.object(llm.openai, "OpenAI") as ctor:
        choice = MagicMock()
        choice.message.content = None
        ctor.return_value.chat.completions.create.return_value.choices = [choice]
        provider = llm.GrokProvider(api_key="xai-test")

        assert provider.complete(system="s", messages=[]) == ""


# ---------------------------------------------------------------------------
# Event-loop safety
# ---------------------------------------------------------------------------

_BLOCKING_SECONDS = 0.4


def _run_with_ticker(coro_factory) -> tuple[object, int]:
    """Run a coroutine while a 10ms ticker shares the loop.

    Returns (result, ticks observed before the coroutine finished).
    """

    async def main():
        ticks = 0
        stop = False

        async def ticker():
            nonlocal ticks
            while not stop:
                await asyncio.sleep(0.01)
                ticks += 1

        task = asyncio.create_task(ticker())
        try:
            result = await coro_factory()
        finally:
            stop = True
            task.cancel()
        return result, ticks

    return asyncio.run(main())


def test_summarize_call_does_not_block_the_event_loop():
    """A slow provider call must not freeze concurrent calls/websockets.

    brain.summarize_call runs in the media-stream `finally` block and in the
    /voice/status handler; a synchronous provider call there stalls every other
    coroutine on the loop for the duration of the request and its backoff.
    """
    provider = MagicMock()

    def slow_complete(**kwargs):
        time.sleep(_BLOCKING_SECONDS)
        return "SUMMARY"

    provider.complete.side_effect = slow_complete

    session = CallSession(call_sid="CA_BLOCK", caller="+15550000000")
    session.add_caller_message("hi")
    session.add_agent_message("hello")

    with patch("agent.brain.get_provider", return_value=provider):
        from agent.brain import summarize_call

        summary, ticks = _run_with_ticker(lambda: summarize_call(session))

    assert summary == "SUMMARY"
    assert session.summary == "SUMMARY"
    # ~40 ticks are available during the blocking window; require a healthy
    # fraction. A blocking call on the loop yields exactly 0.
    assert ticks >= 10, f"event loop was blocked during the provider call ({ticks} ticks)"


