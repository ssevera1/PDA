# Data Flow & Latency Analysis

End-to-end data flows through PDAgent with latency budget analysis.

## Incoming Call Flow

```mermaid
sequenceDiagram
    participant C as Caller
    participant P as PSTN
    participant T as Twilio
    participant A as PDAgent
    participant L as LLM API
    participant S as Session Store

    Note over C,S: Call Initiation (~2-5s total setup)

    C->>P: Dials phone number
    P->>T: SIP INVITE (carrier routing)
    T->>T: Answer call, begin recording

    rect rgb(230, 245, 255)
        Note over T,S: Webhook: POST /voice/incoming
        T->>A: POST /voice/incoming<br/>CallSid, From, FromCity, FromState
        A->>A: Validate Twilio signature (HMAC-SHA1)
        A->>A: Check concurrent call limit (max 10)
        A->>S: store.create(CallSid, caller, city, state)
        S-->>A: CallSession created
        A->>L: generate_greeting(session)<br/>system_prompt + caller context
        Note over A,L: ~500-1500ms (LLM round-trip)
        L-->>A: Greeting text
        A->>S: session.add_agent_message(greeting)
        A-->>T: TwiML: Say greeting + Gather(speech)
    end

    T->>C: Speaks greeting via Polly.Joanna-Neural
    Note over T,C: ~2-4s (TTS synthesis + playback)

    T->>T: Begin listening for speech (Gather)
```

## Conversation Turn Flow

```mermaid
sequenceDiagram
    participant C as Caller
    participant T as Twilio
    participant A as PDAgent
    participant L as LLM API
    participant S as Session Store

    rect rgb(255, 245, 230)
        Note over C,S: Single Conversation Turn (~3-6s total)

        C->>T: Speaks into phone
        Note over C,T: Caller speaks (~2-10s)
        T->>T: Speech-to-text transcription
        Note over T: ~1-2s (ASR processing)

        T->>A: POST /voice/gather<br/>CallSid, SpeechResult
        A->>A: Validate Twilio signature
        A->>S: store.get(CallSid)
        S-->>A: CallSession

        alt SpeechResult is empty
            A-->>T: TwiML: Say "I didn't catch that" + Gather
        else SpeechResult present
            A->>A: Sanitize input (truncate, strip)
            A->>A: Check turn limit (max 20)
            A->>S: session.add_caller_message(text)
            A->>L: respond(session, caller_input)<br/>system_prompt + full message history
            Note over A,L: ~800-2000ms (LLM inference)
            L-->>A: Reply text (max 300 tokens)
            A->>S: session.add_agent_message(reply)

            alt Reply contains "CALL_COMPLETE"
                A->>A: Strip CALL_COMPLETE flag
                Note over A,S: Trigger completion flow (see below)
            else Normal reply
                A-->>T: TwiML: Say reply + Gather(speech)
            end
        end

        T->>C: Speaks reply via Polly.Joanna-Neural
        T->>T: Begin listening (next Gather)
    end

    Note over C,S: Loop repeats for up to 20 caller turns
```

## Call Completion Flow

```mermaid
sequenceDiagram
    participant T as Twilio
    participant A as PDAgent
    participant L as LLM API
    participant S as Session Store
    participant D as Dispatcher
    participant F as JSONL File
    participant TG as Telegram

    rect rgb(230, 255, 230)
        Note over T,TG: Call Completion (~2-5s, non-blocking to caller)

        A->>L: summarize_call(session)<br/>SUMMARY_PROMPT + transcript
        Note over A,L: ~1000-3000ms (summary generation)
        L-->>A: Structured summary text
        A->>S: session.summary = summary

        A->>D: send_notifications(session, summary)
        D->>F: _persist_call() with file lock<br/>Append JSONL record
        Note over D,F: ~1-5ms (local disk write)

        D->>TG: send_call_summary(session, summary)<br/>POST /sendMessage (HTML)
        Note over D,TG: ~200-500ms (Telegram API)

        A->>S: store.remove(CallSid)
    end

    alt Normal completion (CALL_COMPLETE)
        A-->>T: TwiML: Say final reply + Hangup
        T->>T: Terminate call
    else Caller hangup (status callback)
        Note over T,A: POST /voice/status with CallStatus
        A->>A: Detect session still exists -> run completion flow
    end
```

## Latency Budget Analysis

### Per-Turn Latency Breakdown

| Phase | Duration | Notes |
|-------|----------|-------|
| Caller speaks | 2-10s | Variable; depends on utterance length |
| Twilio ASR | 1-2s | Speech-to-text processing |
| Network (Twilio -> PDAgent) | 50-200ms | Depends on deployment location |
| Signature validation | <1ms | HMAC-SHA1 computation |
| Session lookup + sanitization | <1ms | In-memory dict lookup |
| LLM API round-trip | 800-2000ms | **Dominant latency source** |
| Network (PDAgent -> Twilio) | 50-200ms | TwiML response delivery |
| Twilio TTS | 500-1500ms | Neural voice synthesis |
| **Total perceived delay** | **~1.5-4s** | From end of speech to start of reply |

### Latency Optimization Opportunities

```mermaid
graph LR
    subgraph Current["Current Architecture"]
        A[Caller speaks] --> B[Twilio ASR]
        B --> C[Webhook POST]
        C --> D[LLM API call]
        D --> E[TwiML response]
        E --> F[Twilio TTS]
    end

    subgraph Bottleneck["Bottleneck"]
        D
    end

    style D fill:#ff9999
    style Bottleneck fill:#fff0f0,stroke:#ff0000
```

| Optimization | Impact | Complexity | Status |
|-------------|--------|------------|--------|
| Use faster LLM model (e.g., Gemini Flash) | -200-500ms | Low (config change) | Available |
| Deploy closer to Twilio region (us-east-1) | -50-150ms | Medium | Available |
| Stream LLM response + chunked TTS | -500-1000ms | High (requires WebSocket) | Not implemented |
| Pre-warm LLM connection (keep-alive) | -50-100ms | Low | Partially (SDK handles) |
| Reduce prompt size (shorter system prompt) | -50-200ms | Low | Trade-off with quality |

## Data Persistence Flow

```mermaid
flowchart LR
    subgraph Runtime["In-Memory (Runtime)"]
        CS[CallSession]
        MS[Message History]
        CS --> MS
    end

    subgraph Disk["On Disk (Persistent)"]
        JL[call_history.jsonl]
    end

    subgraph External["External (Notification)"]
        TG[Telegram Message]
    end

    CS -->|"On call completion<br/>threading.Lock"| JL
    CS -->|"On call completion<br/>async HTTP POST"| TG

    style Runtime fill:#e6f3ff
    style Disk fill:#e6ffe6
    style External fill:#fff0e6
```

### Data Lifecycle

| Stage | Storage | Durability | TTL |
|-------|---------|------------|-----|
| Active call | In-memory dict | Process lifetime | Max 1 hour (cleanup) |
| Completed call | JSONL file | Disk lifetime | Indefinite |
| Notification | Telegram message | Telegram retention | Indefinite |
| Stale session | In-memory | Cleaned every 5 min | 1 hour max |
