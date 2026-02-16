# ADR-005: Telegram for Real-Time Call Notifications

**Status:** Accepted
**Date:** 2025-01-15
**Deciders:** Project maintainer

## Context

PDAgent needs to notify the owner after each call with a summary of who called, what they wanted, and whether any action is needed. The notification must be:

- **Immediate** - Owner should know about calls within seconds of completion
- **Rich** - Support formatted text with structured call details
- **Mobile-friendly** - Owner is often away from their desk (that's why they have a phone assistant)
- **Low-cost** - Personal project; notification infrastructure should be free or near-free
- **Simple to integrate** - Minimal code and no heavy SDKs

Options considered:

1. **Telegram Bot API** - Free messaging with rich formatting
2. **Email (SMTP/SES)** - Universal but slow and often buried in inboxes
3. **SMS (Twilio)** - Already have Twilio; direct and immediate
4. **Slack Webhooks** - Rich formatting, good for teams
5. **Push notifications (Firebase/APNs)** - Requires custom mobile app

## Decision

Use the **Telegram Bot API** for call notifications:

- Notifications are sent via `POST https://api.telegram.org/bot{TOKEN}/sendMessage`
- Messages use HTML formatting (`parse_mode=HTML`) for structured call reports
- Implementation uses Python's built-in `urllib.request` - no external dependency
- Bot token and chat ID are configured via environment variables
- Notification delivery is optional: if Telegram is not configured, calls still work and persist to disk
- 15-second timeout prevents notification failures from blocking the application

## Consequences

### Positive

- **Zero cost** - Telegram Bot API is completely free with generous rate limits (30 messages/second per bot). No per-message charges.
- **Zero dependencies** - Uses `urllib.request` from Python's standard library. No `python-telegram-bot`, no `requests`, no additional packages.
- **Instant delivery** - Push notifications arrive on phone within 1-2 seconds. Faster than email, comparable to SMS.
- **Rich formatting** - HTML parse mode supports bold, italic, code blocks, and line breaks. Call reports are well-structured and readable.
- **Cross-platform** - Telegram apps for iOS, Android, Windows, macOS, Linux, and web. Owner can receive notifications on any device.
- **Simple setup** - Create bot via @BotFather (2 minutes), get chat ID, set two environment variables. No OAuth, no webhook registration, no API key management.
- **Graceful degradation** - If Telegram fails (network issue, invalid token), the call is still persisted to JSONL. Notification failure is logged but doesn't affect call handling.

### Negative

- **Single channel** - If the owner doesn't use Telegram, they must install it or miss notifications. Mitigated by Telegram's wide availability and lightweight desktop/mobile apps.
- **No delivery confirmation** - The API confirms message acceptance, not delivery. If the owner's device is offline, notifications queue but there's no visibility into this from PDAgent's side.
- **No conversation threading** - Each call notification is a standalone message. No threading or grouping by caller. At personal-use volumes, this is not an issue.
- **Privacy consideration** - Call details (caller number, transcript summary) pass through Telegram's servers. Mitigated by Telegram's encryption and the fact that summaries, not full transcripts, are sent.

### Trade-offs Accepted

The primary trade-off is **vendor lock-in to Telegram for notification simplicity**. Building a multi-channel notification system (email + SMS + push) would provide redundancy but at the cost of significant complexity, configuration burden, and potentially per-message costs. For a personal assistant where the owner can install Telegram, the single-channel approach provides 95% of the value at 10% of the complexity.

## Alternatives Rejected

| Alternative | Why Rejected |
|-------------|-------------|
| **Email (SMTP/SES)** | Slower delivery (seconds to minutes), often lands in spam/promotions, requires SMTP server or SES setup, not ideal for urgent call notifications. Would be a good secondary channel. |
| **SMS (Twilio)** | Per-message cost ($0.0079/msg). Already using Twilio for voice; adding SMS creates circular dependency concerns. Character limit (160) too short for call summaries. |
| **Slack** | Team-oriented, not personal. Requires workspace setup, OAuth app, webhook URLs. Overkill for a single-user notification. Would be appropriate if PDAgent served a team. |
| **Firebase/APNs** | Requires building and maintaining a custom mobile app just to receive push notifications. Massive overhead for a simple notification use case. |
