# C4 Level 2: Container Diagram

The internal containers (deployable units and data stores) that make up PDAgent.

```mermaid
C4Container
    title Container Diagram - PDAgent

    Person(caller, "Caller", "Phone caller")
    Person(owner, "Owner", "Receives notifications")

    System_Boundary(pdagent_system, "PDAgent System") {
        Container(webapp, "FastAPI Application", "Python 3.12, FastAPI, Uvicorn", "Handles Twilio webhooks, orchestrates AI conversations, dispatches notifications")
        ContainerDb(sessions, "In-Memory Session Store", "Python dict", "Holds active CallSession objects keyed by CallSid; max 10 concurrent; 1-hour TTL")
        ContainerDb(calllog, "Call History File", "JSONL on disk", "Append-only log of completed call records at data/call_history.jsonl")
    }

    System_Ext(twilio, "Twilio", "Voice platform")
    System_Ext(llm, "LLM API", "Claude / Grok / Gemini")
    System_Ext(telegram, "Telegram", "Bot API")

    Rel(caller, twilio, "Speaks over phone")
    Rel(twilio, webapp, "POST /voice/incoming, /voice/gather, /voice/status", "HTTPS + X-Twilio-Signature")
    Rel(webapp, twilio, "TwiML XML responses", "Say, Gather, Hangup")
    Rel(webapp, sessions, "Create/Read/Delete sessions", "Thread-safe dict operations")
    Rel(webapp, llm, "Generate greeting, response, summary", "HTTPS, API key auth")
    Rel(webapp, calllog, "Append call record on completion", "Thread-safe file lock")
    Rel(webapp, telegram, "POST /sendMessage", "HTTPS, bot token auth")
    Rel(telegram, owner, "Push notification")
```

## Container Details

### FastAPI Application

| Attribute | Value |
|-----------|-------|
| Runtime | Python 3.12, Uvicorn ASGI |
| Framework | FastAPI 0.115.6 |
| Endpoints | `POST /voice/incoming`, `POST /voice/gather`, `POST /voice/status`, `GET /health`, `GET /` |
| Middleware | RateLimitMiddleware (30 req/min), SecurityHeadersMiddleware (CSP, X-Frame-Options) |
| Background Tasks | Stale session cleanup (every 5 min, removes sessions > 1 hour old) |
| Deployment | Docker container, cloud PaaS, or bare EC2 + ngrok |

### In-Memory Session Store

| Attribute | Value |
|-----------|-------|
| Implementation | `dict[str, CallSession]` behind `ConversationStore` class |
| Capacity | Max 10 concurrent sessions (enforced at `/voice/incoming`) |
| TTL | 1 hour (background cleanup task) |
| Thread Safety | Standard Python dict (single-threaded asyncio event loop) |
| Durability | None - sessions lost on process restart |
| Session Data | CallSid, caller number, city/state, start time, message history, escalation flag, summary |

### Call History File

| Attribute | Value |
|-----------|-------|
| Format | JSON Lines (one JSON object per line) |
| Location | `data/call_history.jsonl` (configurable via `DATA_DIR` env var) |
| Thread Safety | `threading.Lock()` for file writes |
| Fields | call_sid, caller, caller_city, caller_state, started_at, duration_seconds, duration_display, summary, timestamp, turn_count |
| Size Limits | call_sid: 50 chars, caller: 200 chars, summary: 5000 chars |
| Docker | Mounted as volume at `/app/data` |

## Scaling Considerations

This architecture is designed for a **single-instance personal assistant** (1-2 concurrent calls typical). Scaling beyond a single instance would require:

1. **Session store** -> Redis or similar shared state store
2. **Call history** -> PostgreSQL or time-series database
3. **Load balancing** -> Sticky sessions or session-aware routing
4. **Twilio webhook URLs** -> Behind a load balancer with consistent routing
