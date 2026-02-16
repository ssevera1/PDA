# ADR-006: CALL_COMPLETE Flag for Conversation Termination

**Status:** Accepted
**Date:** 2025-01-15
**Deciders:** Project maintainer

## Context

PDAgent needs a reliable mechanism for the AI agent to signal that a conversation has reached its natural conclusion. When the caller's request has been handled (message taken, callback scheduled, question answered), the agent should be able to end the call gracefully rather than continuing an unnecessary conversation loop.

The challenge is that the LLM produces free-form text, and the system needs to distinguish between "the AI wants to say something" and "the AI wants to say something AND end the call." The termination signal must be:

- **Reliable** - Detectable with simple string matching, not semantic analysis
- **Unambiguous** - Cannot be confused with conversational text
- **Clean** - Removable from the response before speaking to the caller
- **Prompt-friendly** - Easy to explain to the LLM in the system prompt

Options considered:

1. **In-band text flag** (`CALL_COMPLETE`) - Special string appended to the LLM response
2. **Structured output** (JSON with `action` field) - LLM returns JSON with separate text and action fields
3. **Tool use / function calling** - LLM calls an `end_call` function
4. **Sentiment/intent analysis** - Separate model detects conversation completion
5. **Fixed turn count** - Always end after N turns

## Decision

Use an **in-band text flag**: the LLM appends `CALL_COMPLETE` to its response when the conversation should end.

Implementation:
- The system prompt instructs the agent: *"When the conversation is complete, end your final message with CALL_COMPLETE"*
- `brain.respond()` checks for `"CALL_COMPLETE"` in the LLM response
- If found, the flag is stripped and `is_complete=True` is returned
- The webhook handler sends the cleaned response with a `<Hangup/>` TwiML element
- A hard turn limit (20) serves as a safety net if the LLM never signals completion

## Consequences

### Positive

- **Extreme simplicity** - Detection is `"CALL_COMPLETE" in response`. No JSON parsing, no tool call handling, no additional API calls.
- **Provider-agnostic** - Works with any LLM that can follow instructions. No dependency on tool use, structured output, or provider-specific features. Works equally well with Claude, Grok, and Gemini.
- **Reliable** - `CALL_COMPLETE` is an unusual enough string that it won't appear in natural conversation. Simple string matching is more robust than semantic analysis.
- **Graceful** - The agent includes a final farewell message alongside the flag. The caller hears "Thank you for calling, goodbye!" before the call ends, not an abrupt disconnection.
- **Testable** - Easy to mock and assert in tests. No complex structured output to validate.

### Negative

- **Fragile to prompt drift** - If the LLM is updated and stops following the CALL_COMPLETE instruction reliably, calls could loop until the 20-turn safety limit. Mitigated by the safety limit and by testing with each provider.
- **Not extensible** - Only supports one signal (end call). If future features need signals like "transfer to human" or "play hold music," the pattern would need to evolve to support multiple flags or switch to structured output.
- **Pollutes response text** - The flag must be stripped from the response before TTS. If stripping fails or the flag appears mid-sentence, the caller could hear "CALL_COMPLETE" spoken aloud. Mitigated by simple string replacement.
- **No structured metadata** - Cannot carry additional data like "reason for ending" or "urgency level" with the termination signal. The summary prompt handles this separately.

### Trade-offs Accepted

The trade-off is **extensibility for simplicity and provider compatibility**. Structured output (JSON) or tool use would provide a cleaner, more extensible signal mechanism but would depend on provider-specific features, require JSON parsing in the response path, and introduce failure modes (malformed JSON, missing fields). For a system that only needs one signal ("conversation is done"), the in-band flag is the minimum viable solution.

The 20-turn safety limit ensures that even if the flag mechanism fails completely, calls cannot loop indefinitely. This defense-in-depth approach makes the flag pattern safe to use despite its fragility.

## Alternatives Rejected

| Alternative | Why Rejected |
|-------------|-------------|
| **Structured output (JSON)** | Requires all providers to reliably produce valid JSON. Adds JSON parsing to the response path. Provider support varies (Claude supports it well, others less reliably). Over-engineered for a single boolean signal. |
| **Tool use / function calling** | Most robust solution but not universally supported across providers. Adds complexity to the LLM integration layer. Would require provider-specific tool call implementations. Good migration target if PDAgent adds more agent capabilities. |
| **Sentiment analysis** | Unreliable. A second model call would add latency and cost. Determining "is the conversation done?" is a nuanced judgment that even humans disagree on. |
| **Fixed turn count** | Too rigid. Some calls resolve in 2 turns (wrong number), others need 15 (complex message). A fixed count either cuts off legitimate conversations or forces unnecessary ones. The 20-turn limit serves only as a safety net. |
