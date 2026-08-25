"""LLM provider abstraction — normalizes Claude, Grok, and Gemini APIs."""

from __future__ import annotations

from abc import ABC, abstractmethod
import time

import anthropic
import openai

from config import get_settings, LLMProvider

# ---------------------------------------------------------------------------
# Retry and timeout configuration
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_INITIAL_BACKOFF_SECONDS = 1.0
_TIMEOUT_SECONDS = 60.0


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseLLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, messages: list[dict], max_tokens: int = 300) -> str:
        """Send a chat completion request and return the assistant text."""


# ---------------------------------------------------------------------------
# Claude (Anthropic native SDK)
# ---------------------------------------------------------------------------

class ClaudeProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str | None = None):
        self._client = anthropic.Anthropic(api_key=api_key, timeout=_TIMEOUT_SECONDS)
        self._model = model or "claude-sonnet-4-6"

    def complete(self, system: str, messages: list[dict], max_tokens: int = 300) -> str:
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,
                )
                return response.content[0].text
            except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
                if attempt == _MAX_RETRIES - 1:
                    raise
                backoff = _INITIAL_BACKOFF_SECONDS * (2 ** attempt)
                time.sleep(backoff)


# ---------------------------------------------------------------------------
# OpenAI-compatible providers (Grok, Gemini)
# ---------------------------------------------------------------------------

class _OpenAICompatibleProvider(BaseLLMProvider):
    """Shared logic for any provider that exposes an OpenAI-compatible API."""

    def __init__(self, api_key: str, base_url: str, model: str):
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=_TIMEOUT_SECONDS)
        self._model = model

    def complete(self, system: str, messages: list[dict], max_tokens: int = 300) -> str:
        full_messages = [{"role": "system", "content": system}] + messages
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    messages=full_messages,
                )
                text = response.choices[0].message.content
                return text or ""
            except (openai.APIConnectionError, openai.APITimeoutError) as e:
                if attempt == _MAX_RETRIES - 1:
                    raise
                backoff = _INITIAL_BACKOFF_SECONDS * (2 ** attempt)
                time.sleep(backoff)


class GrokProvider(_OpenAICompatibleProvider):
    def __init__(self, api_key: str, model: str | None = None):
        super().__init__(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
            model=model or "grok-3-mini",
        )


class GeminiProvider(_OpenAICompatibleProvider):
    def __init__(self, api_key: str, model: str | None = None):
        super().__init__(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model=model or "gemini-2.5-flash",
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_provider: BaseLLMProvider | None = None


def get_provider() -> BaseLLMProvider:
    """Return a cached LLM provider instance based on settings."""
    global _provider
    if _provider is not None:
        return _provider

    settings = get_settings()
    if settings.llm_provider == LLMProvider.claude:
        _provider = ClaudeProvider(settings.anthropic_api_key, settings.llm_model)
    elif settings.llm_provider == LLMProvider.grok:
        _provider = GrokProvider(settings.xai_api_key, settings.llm_model)
    elif settings.llm_provider == LLMProvider.gemini:
        _provider = GeminiProvider(settings.google_api_key, settings.llm_model)
    else:
        raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
    return _provider


def reset_provider() -> None:
    """Clear the cached provider (useful for tests)."""
    global _provider
    _provider = None
