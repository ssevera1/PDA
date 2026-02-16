# ADR-001: In-Memory Session Store Over External Database

**Status:** Accepted
**Date:** 2025-01-15
**Deciders:** Project maintainer

## Context

PDAgent needs to maintain conversational state during phone calls. Each call session tracks the caller's identity, message history, and metadata. The session must persist for the duration of the call (typically 1-10 minutes) and be accessible with minimal latency since it sits in the critical path of every conversation turn.

Options considered:

1. **In-memory Python dict** - Store sessions in application memory
2. **Redis** - External in-memory key-value store with persistence
3. **SQLite** - Embedded relational database
4. **PostgreSQL** - Full relational database

## Decision

Use an **in-memory Python dictionary** wrapped in a `ConversationStore` class (`store/conversations.py`), with sessions keyed by Twilio `CallSid`.

A background cleanup task removes sessions older than 1 hour every 5 minutes to prevent memory leaks from orphaned sessions.

## Consequences

### Positive

- **Sub-microsecond access latency** - No network round-trip or disk I/O in the conversation critical path. Session lookup is a dict lookup.
- **Zero infrastructure** - No database to provision, configure, secure, backup, or maintain. Reduces operational burden to zero for state management.
- **Simple deployment** - Single process, no external dependencies for runtime state. Works identically in Docker, PaaS, and bare metal.
- **Sufficient for use case** - Personal assistant handles 1-2 concurrent calls typically, with a hard cap at 10. Memory usage is negligible (~1KB per session).

### Negative

- **No horizontal scaling** - Sessions are process-local. Running multiple instances would require sticky sessions or a shared store (Redis). This is an acceptable limitation for a personal assistant.
- **No crash recovery** - If the process restarts mid-call, active sessions are lost. Callers would hear a Twilio error or be disconnected. Mitigated by the fact that calls are short-lived (minutes, not hours).
- **No session inspection** - No external tools to query active sessions for debugging. Mitigated by logging.

### Trade-offs Accepted

The primary trade-off is **durability for simplicity**. For a personal phone assistant that typically handles one call at a time, the risk of losing an active session to a crash is low and the impact (caller redials) is manageable. The alternative of adding Redis would introduce an external dependency, increase deployment complexity, and add ~1-5ms latency per session operation - all for a durability guarantee that provides minimal value in this context.

## Alternatives Rejected

| Alternative | Why Rejected |
|-------------|-------------|
| **Redis** | Over-engineered for 1-10 concurrent sessions. Adds infrastructure dependency, network latency, and operational burden. Would be the right choice if scaling to multiple instances. |
| **SQLite** | Adds disk I/O to the critical path. WAL mode would help but still slower than memory. Crash recovery benefit is marginal for short-lived sessions. |
| **PostgreSQL** | Massively over-engineered. Would add 5-20ms per session operation, require a managed database, and need connection pooling. Appropriate for multi-tenant SaaS, not a personal assistant. |
