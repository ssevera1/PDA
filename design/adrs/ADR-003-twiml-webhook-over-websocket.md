# ADR-003: TwiML Webhook Pattern Over WebSocket/WebRTC

**Status:** Accepted
**Date:** 2025-01-15
**Deciders:** Project maintainer

## Context

PDAgent needs to handle voice phone calls: receiving caller speech, processing it through an AI model, and speaking back a response. There are several architectural patterns for voice AI applications:

1. **TwiML Webhooks** - Twilio calls HTTP endpoints; server returns XML instructions (Say, Gather, Hangup). Twilio handles ASR and TTS.
2. **Twilio Media Streams (WebSocket)** - Twilio streams raw audio via WebSocket. Server handles ASR, AI processing, and TTS, then streams audio back.
3. **WebRTC Direct** - Browser/app connects directly for real-time audio. Server handles everything.
4. **Twilio Programmable Voice + External ASR/TTS** - Use Twilio for call handling but external services for speech processing.

Key requirements:
- Must work with regular phone calls (PSTN), not just browser-based
- Must support any phone (no app installation)
- Latency should be acceptable for natural conversation
- Deployment should be simple (personal project)

## Decision

Use the **TwiML webhook pattern** where Twilio handles all audio processing (ASR and TTS) and PDAgent only handles text:

1. Twilio receives the call and transcribes caller speech using its built-in ASR
2. Twilio POSTs the transcription to PDAgent's `/voice/gather` endpoint
3. PDAgent processes the text through the LLM and returns TwiML XML
4. Twilio synthesizes speech using Amazon Polly (Neural voice) and plays it back
5. The loop repeats with a new `<Gather>` element

## Consequences

### Positive

- **Dramatically simpler architecture** - Server only handles text, not audio streams. No audio encoding/decoding, no WebSocket connection management, no audio buffer handling.
- **No ASR/TTS infrastructure** - Twilio provides Google/Amazon-grade speech recognition and neural TTS at no additional cost beyond per-minute call pricing. No need to integrate Whisper, Deepgram, ElevenLabs, etc.
- **Stateless HTTP** - Each interaction is a standard HTTP request-response. No persistent connections to manage. Trivially scalable, debuggable, and deployable.
- **Universal phone compatibility** - Works with any phone on any carrier. No app, no browser, no special client. Caller dials a number and talks.
- **Simple deployment** - Any HTTP server works. No WebSocket support needed. Works behind standard reverse proxies, load balancers, and PaaS platforms.
- **Robust error handling** - If PDAgent crashes or times out, Twilio falls back to its own error handling. No dropped audio streams or orphaned connections.

### Negative

- **Higher per-turn latency** - Each turn requires: speech finish detection -> ASR -> HTTP POST -> LLM -> HTTP response -> TTS -> playback. The full round-trip adds ~1-3 seconds of perceived delay compared to streaming approaches that can begin speaking while still generating.
- **No interruption support** - Caller cannot interrupt the AI mid-speech (barge-in). They must wait for the full response to play before speaking. This can feel unnatural for long responses (mitigated by keeping responses to 2-3 sentences).
- **Turn-based, not streaming** - Cannot stream partial LLM output to the caller. The full response must be generated before TTS begins. WebSocket approaches can start speaking the first sentence while generating the rest.
- **Twilio dependency** - Fully dependent on Twilio for audio handling. No ability to use custom ASR models or alternative TTS voices beyond what Twilio offers.

### Trade-offs Accepted

The primary trade-off is **latency for simplicity**. The TwiML pattern adds 1-3 seconds of perceived delay per turn compared to a streaming WebSocket architecture. This is accepted because:

1. **PDAgent's responses are short** (2-3 sentences, <300 tokens). The latency difference between streaming and batch is small for short outputs.
2. **Phone conversations have natural pauses.** Callers expect a brief delay when talking to an "assistant" - it feels more like being put on hold than a lag.
3. **The complexity reduction is massive.** A WebSocket streaming architecture would require: audio codec handling, VAD (voice activity detection), streaming ASR integration, streaming TTS integration, audio buffer management, WebSocket lifecycle management, and real-time audio synchronization. This would likely triple the codebase and add 3-5 external service integrations.
4. **The use case tolerates it.** PDAgent is a call screener, not a real-time voice agent for customer support. Callers are leaving messages or requesting callbacks, not having rapid-fire conversations.

## Alternatives Rejected

| Alternative | Why Rejected |
|-------------|-------------|
| **Twilio Media Streams** | Requires WebSocket server, audio codec handling (mulaw), external ASR (Deepgram/Whisper), external TTS (ElevenLabs/PlayHT), and audio streaming synchronization. 5-10x complexity increase for 1-2s latency improvement. Appropriate for real-time voice agents, not a personal call screener. |
| **WebRTC Direct** | Requires client-side code (browser/app). Cannot work with regular phone calls. Eliminates the core use case of screening PSTN calls. |
| **Hybrid (TwiML + External TTS)** | Using Twilio for ASR but external TTS (ElevenLabs) via `<Play>` would give better voice quality but add infrastructure, cost, and latency for the TTS API call. Polly Neural voices are good enough. |
