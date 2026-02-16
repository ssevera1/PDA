# C4 Level 1: System Context Diagram

How PDAgent fits into the broader ecosystem of users and external systems.

```mermaid
C4Context
    title System Context Diagram - PDAgent

    Person(caller, "Caller", "Anyone calling the owner's phone number")
    Person(owner, "Owner", "Person who deployed PDAgent to screen and manage calls")

    System(pdagent, "PDAgent", "AI-powered personal phone assistant that answers calls, converses with callers, and notifies the owner")

    System_Ext(twilio, "Twilio Voice Platform", "Handles PSTN connectivity, speech-to-text, and text-to-speech via TwiML")
    System_Ext(llm, "LLM Provider", "AI language model API (Anthropic Claude, xAI Grok, or Google Gemini)")
    System_Ext(telegram, "Telegram Bot API", "Instant messaging platform for delivering call notifications")
    System_Ext(pstn, "PSTN / Carrier Network", "Public telephone network connecting caller to Twilio")

    Rel(caller, pstn, "Dials phone number")
    Rel(pstn, twilio, "Routes call via SIP/carrier interconnect")
    Rel(twilio, pdagent, "Sends TwiML webhooks (HTTPS POST)", "CallSid, SpeechResult, status events")
    Rel(pdagent, twilio, "Returns TwiML instructions", "Say, Gather, Hangup")
    Rel(pdagent, llm, "Sends conversation context", "HTTPS, max 300 tokens/turn")
    Rel(llm, pdagent, "Returns generated response")
    Rel(pdagent, telegram, "Sends call summary report", "HTTPS POST, HTML-formatted")
    Rel(telegram, owner, "Delivers notification", "Push notification to mobile/desktop")

    UpdateRelStyle(caller, pstn, $offsetY="-10")
    UpdateRelStyle(pdagent, telegram, $offsetX="-60")
```

## Key Observations

- **PDAgent never directly communicates with the caller.** All voice interaction is mediated through Twilio, which handles speech recognition (ASR) and text-to-speech (TTS).
- **The owner does not interact with PDAgent during a call.** They receive a post-call summary via Telegram after the conversation concludes.
- **LLM calls are synchronous and blocking.** Each caller utterance triggers a round-trip to the LLM provider before Twilio can speak the response. This introduces latency in the conversation loop (see [data-flow.md](data-flow.md) for latency analysis).
- **Three external API dependencies** create three potential failure points. Twilio is the most critical; LLM failure results in a degraded experience; Telegram failure only affects notifications.

## Trust Boundaries

| Boundary | Inside | Outside |
|----------|--------|---------|
| PDAgent process | Session state, LLM prompts, call history | All external APIs |
| Twilio signature validation | Authenticated webhook requests | Unsigned/tampered requests (rejected 403) |
| Rate limiter | Requests within 30/min threshold | Excess requests (rejected 429) |
