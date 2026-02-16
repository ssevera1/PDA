# ADR-007: Layered Security Middleware Architecture

**Status:** Accepted
**Date:** 2025-01-15
**Deciders:** Project maintainer

## Context

PDAgent exposes HTTP endpoints to the internet (required for Twilio webhooks). Although the intended client is only Twilio, the endpoints are publicly accessible and must be protected against:

- **Abuse** - Automated requests that consume LLM API credits or exhaust resources
- **Injection** - Malicious input in caller-supplied fields (SpeechResult, CallSid)
- **Spoofing** - Forged webhook requests pretending to be from Twilio
- **Resource exhaustion** - Too many concurrent calls consuming memory and LLM budget
- **Session leaks** - Orphaned sessions accumulating in memory

The security architecture must balance protection with simplicity. Over-engineering security for a personal project creates maintenance burden; under-engineering creates real risk (LLM API costs from abuse).

## Decision

Implement a **layered security architecture** with four complementary mechanisms:

### Layer 1: Rate Limiting (security.py - RateLimitMiddleware)
- Sliding window rate limiter: 30 requests/minute per IP address
- Applied only to `/voice/*` endpoints (health/root excluded)
- Returns HTTP 429 with `Retry-After` header when exceeded
- Automatic cleanup of stale rate limit entries

### Layer 2: Request Authentication (voice/twilio_webhook.py)
- Twilio signature validation using `RequestValidator` with HMAC-SHA1
- Every `/voice/gather` and `/voice/status` request verified against `X-Twilio-Signature` header
- Returns HTTP 403 for invalid signatures
- Uses `TWILIO_AUTH_TOKEN` for HMAC computation

### Layer 3: Input Sanitization (voice/twilio_webhook.py)
- `_sanitize_field()` applied to all caller-supplied input
- Truncation to maximum length (prevents oversized payloads)
- Newline/carriage return stripping (prevents log injection)
- Applied to: SpeechResult, CallSid, From, FromCity, FromState

### Layer 4: Resource Limits
- **Concurrent call cap**: Max 10 simultaneous calls (checked at `/voice/incoming`)
- **Turn limit**: Max 20 caller turns per call (checked at `/voice/gather`)
- **Session TTL**: 1-hour maximum session lifetime (background cleanup every 5 min)
- **LLM token limit**: Max 300 tokens per response (prevents runaway generation)

### Response Hardening (security.py - SecurityHeadersMiddleware)
- `Content-Security-Policy: default-src 'none'` - No resource loading
- `X-Frame-Options: DENY` - No iframe embedding
- `X-Content-Type-Options: nosniff` - No MIME sniffing
- `Referrer-Policy: strict-origin-when-cross-origin` - Minimal referrer leakage

### LLM Prompt Security (agent/prompts.py)
- System prompt includes explicit anti-jailbreak directives
- Agent instructed to never reveal system instructions
- Agent instructed to ignore role-change requests
- Agent instructed to not execute commands or provide system info

## Consequences

### Positive

- **Defense in depth** - No single security layer is a single point of failure. Rate limiting + signature validation + input sanitization + resource limits create overlapping protection.
- **Cost protection** - Rate limiting and concurrent call caps prevent abuse that would consume LLM API credits. The 20-turn limit caps per-call LLM costs.
- **Zero external dependencies** - All security mechanisms are implemented in application code. No WAF, no API gateway, no external rate limiting service.
- **Transparent** - Each security layer logs its actions (rate limit hits, invalid signatures, stale session cleanup). Easy to audit and debug.
- **Proportionate** - Security measures are calibrated to the threat model (personal project exposed to internet) without enterprise-level complexity.

### Negative

- **Single-instance rate limiting** - Rate limit state is in-memory. Multiple instances would not share rate limit counters. Acceptable for single-instance deployment.
- **IP-based rate limiting** - Can be circumvented with IP rotation. Twilio webhooks come from known IP ranges, but rate limiting is applied by requester IP, not Twilio-specific. Twilio signature validation is the primary authentication.
- **No WAF** - No protection against sophisticated L7 attacks. Mitigated by the minimal attack surface (3 POST endpoints, no user-facing UI, no file uploads).
- **No audit log** - Security events are logged to stdout but not to a persistent audit trail. For a personal project, application logs (captured by Docker/systemd) are sufficient.

### Trade-offs Accepted

The trade-off is **enterprise security features for operational simplicity**. A production SaaS would add: WAF (Cloudflare/AWS WAF), API gateway with OAuth, persistent audit logging, IP allowlisting for Twilio, anomaly detection, and security monitoring. These add significant complexity and cost that are disproportionate for a personal assistant. The implemented layers protect against the realistic threats (abuse, spoofing, resource exhaustion) without the operational burden of enterprise security infrastructure.

## Security Model Summary

```
Internet Request
    │
    ▼
[Rate Limiter] ────── 429 if >30 req/min per IP
    │
    ▼
[Security Headers] ── Adds CSP, X-Frame-Options, etc.
    │
    ▼
[Twilio Signature] ── 403 if HMAC-SHA1 invalid
    │
    ▼
[Input Sanitization] ─ Truncate, strip control chars
    │
    ▼
[Resource Limits] ──── 503 if >10 concurrent calls
    │                   End call if >20 turns
    │                   Remove session if >1 hour
    ▼
[LLM Prompt Guard] ── Resist jailbreak, no system info leak
    │
    ▼
[Business Logic] ──── Process legitimate request
```
