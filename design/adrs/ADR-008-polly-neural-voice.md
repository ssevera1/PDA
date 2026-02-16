# ADR-008: Amazon Polly Neural Voice for Text-to-Speech

**Status:** Accepted
**Date:** 2025-01-15
**Deciders:** Project maintainer

## Context

PDAgent speaks to callers through Twilio's TwiML `<Say>` element, which supports multiple TTS engines and voices. The voice directly impacts caller experience - it's the "face" of the assistant. The voice must be:

- **Natural-sounding** - Callers should feel like they're talking to a professional assistant, not a robot
- **Feminine** - Consistent with the default agent name "Sophie"
- **Compatible with Twilio** - Must work within Twilio's `<Say>` element
- **Low-latency** - TTS synthesis time adds to per-turn delay

Twilio's `<Say>` element supports:
1. **Standard voices** - Basic concatenative TTS (robotic, low latency)
2. **Amazon Polly voices** - Standard and Neural variants
3. **Google Cloud TTS** - Standard and WaveNet variants

Voice options explored during development (visible in git history):
- `Google.en-US-Studio-O` - Google Studio voice
- `Polly.Joanna` - Amazon Polly standard voice
- `Polly.Joanna-Neural` - Amazon Polly neural voice

## Decision

Use **`Polly.Joanna-Neural`** (Amazon Polly Neural TTS) as the voice for all `<Say>` elements.

Configuration in `twilio_webhook.py`:
```python
def _say(text: str) -> str:
    return f'<Say voice="Polly.Joanna-Neural">{text}</Say>'
```

## Consequences

### Positive

- **Natural speech quality** - Polly Neural voices use deep learning for significantly more natural prosody, intonation, and rhythm compared to standard voices. Callers perceive a professional assistant rather than a robotic system.
- **Proven Twilio compatibility** - Polly voices are first-class citizens in Twilio's `<Say>` element. No additional configuration, API keys, or external services needed. Just specify the voice name in the XML attribute.
- **Consistent persona** - Joanna is a US English feminine voice that matches the "Sophie" assistant persona. Consistent voice across all interactions builds caller familiarity.
- **No additional cost** - Twilio includes Polly Neural voice synthesis in the per-minute call pricing. No separate AWS Polly billing or API key management.
- **Low integration complexity** - Voice selection is a single string attribute on the `<Say>` element. No SDK, no API calls, no audio file management.

### Negative

- **No voice customization** - Cannot adjust speaking rate, pitch, emphasis, or add pauses beyond what Polly Neural interprets from the text. SSML support in Twilio's `<Say>` is limited.
- **Not the most natural available** - ElevenLabs, PlayHT, and Google's Studio voices can sound more natural but require external API integration, audio streaming, and additional cost. Polly Neural is "good enough" for phone quality audio.
- **Twilio vendor lock-in** - Voice selection is coupled to Twilio's supported voice list. Migrating to a different telephony provider would require voice re-evaluation.
- **English-only** - Joanna is a US English voice. Supporting other languages would require voice switching logic and multilingual prompt engineering.

### Trade-offs Accepted

The trade-off is **peak voice quality for integration simplicity**. External TTS services (ElevenLabs, PlayHT) offer more natural voices with voice cloning, emotion control, and fine-grained SSML. However, they require:

1. A separate API integration with authentication
2. Audio file generation and hosting (or streaming)
3. Switching from `<Say>` to `<Play>` in TwiML (with pre-generated audio URLs)
4. Additional per-character costs ($0.15-0.30 per 1000 characters)
5. Additional latency for the TTS API round-trip

For a personal call screener where conversations are brief and professional, Polly.Joanna-Neural provides a natural enough voice to maintain the assistant illusion without any of this complexity.

### Voice Selection History

The git history shows experimentation with different voices:

| Voice | Outcome | Issue |
|-------|---------|-------|
| `Google.en-US-Studio-O` | Tried | Compatibility or quality issues in Twilio context |
| `Polly.Joanna` (standard) | Tried | Too robotic; standard Polly lacks neural quality |
| `Polly.Joanna-Neural` | **Selected** | Best balance of quality, compatibility, and simplicity |

## Alternatives Rejected

| Alternative | Why Rejected |
|-------------|-------------|
| **Google Studio voices** | Tested but encountered compatibility issues with Twilio's `<Say>` element. Neural Polly was more reliable. |
| **ElevenLabs** | Highest quality voices available but requires separate API integration, audio streaming via `<Play>`, per-character costs, and adds latency. Over-engineered for phone-quality audio on a personal project. |
| **Standard Polly (non-Neural)** | Too robotic. The quality gap between standard and neural Polly is significant and immediately noticeable to callers. Neural is worth the (zero) additional cost within Twilio. |
| **Twilio default voice** | Basic concatenative TTS. Sounds obviously robotic. Would undermine the professional assistant persona. |
