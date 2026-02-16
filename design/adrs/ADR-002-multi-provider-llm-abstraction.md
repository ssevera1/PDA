# ADR-002: Multi-Provider LLM Abstraction Layer

**Status:** Accepted
**Date:** 2025-01-15
**Deciders:** Project maintainer

## Context

PDAgent relies on a large language model (LLM) for three core functions: generating greetings, producing conversational responses, and summarizing completed calls. The LLM market is rapidly evolving with significant differences in cost, latency, quality, and availability across providers.

At the time of development, the primary options were:

1. **Anthropic Claude** (Sonnet) - High quality, moderate cost, native SDK
2. **xAI Grok** - Competitive pricing, OpenAI-compatible API
3. **Google Gemini** (Flash) - Low cost, fast inference, OpenAI-compatible API

A key consideration is that the phone conversation loop is latency-sensitive: the caller waits for the AI to respond after each utterance. LLM inference is the dominant latency source (800-2000ms per turn).

## Decision

Implement a **provider abstraction layer** (`agent/llm.py`) using the Strategy pattern:

- `BaseLLMProvider` abstract base class defines the `generate()` interface
- `ClaudeProvider` uses the native Anthropic SDK (system prompt as separate parameter)
- `_OpenAICompatibleProvider` base class handles providers that support the OpenAI API format
  - `GrokProvider` extends it with xAI-specific configuration
  - `GeminiProvider` extends it with Google-specific configuration
- `get_provider()` factory function creates and caches the appropriate provider based on `LLM_PROVIDER` config

The provider is selected at startup via the `LLM_PROVIDER` environment variable and cached as a singleton.

## Consequences

### Positive

- **Cost optimization** - Owner can switch to the cheapest provider that meets quality needs. Gemini Flash is significantly cheaper than Claude Sonnet for comparable quality in short conversational turns.
- **Latency optimization** - Different providers have different inference speeds. Gemini Flash typically has lower latency than Claude Sonnet, which directly improves caller experience.
- **Resilience** - If one provider has an outage or rate-limits, the owner can switch to another by changing a single environment variable and restarting.
- **Future-proofing** - New providers can be added by implementing a single `generate()` method. The OpenAI-compatible base class makes this trivial for any provider that supports the OpenAI API format.
- **Clean separation** - Business logic in `brain.py` is completely decoupled from provider-specific SDK details.

### Negative

- **Prompt behavior variance** - The same system prompt may produce different tone, quality, or adherence across providers. Prompt engineering must be tested against all supported providers.
- **Feature parity gaps** - Claude supports system prompts natively; OpenAI-compatible providers require prepending as a system message. Some providers may support features (tool use, streaming) that others don't.
- **Testing surface** - Each provider path needs testing. Currently mitigated by mocking the provider in tests.
- **Singleton caching** - Provider is cached at first call. Changing `LLM_PROVIDER` at runtime requires calling `reset_provider()` (primarily used in tests).

### Trade-offs Accepted

The abstraction adds a thin layer of complexity (~110 lines) in exchange for significant operational flexibility. The trade-off of potential behavioral variance across providers is accepted because the conversational use case (short, professional phone responses) is tolerant of minor style differences, and the cost/latency benefits of provider choice are substantial for a self-hosted personal project.

## Alternatives Rejected

| Alternative | Why Rejected |
|-------------|-------------|
| **Single provider (Claude only)** | Locks into one provider's pricing and availability. No fallback if Anthropic has an outage. Misses cost optimization opportunity. |
| **LangChain / LiteLLM** | Heavy dependencies for a simple `generate()` interface. PDAgent only needs text completion, not chains, agents, or RAG. The abstraction layer is ~110 lines vs. thousands in these frameworks. |
| **Runtime provider switching** | Over-engineered. Switching mid-call would create inconsistent conversation tone. Config-time selection is sufficient; restart takes <5 seconds. |
