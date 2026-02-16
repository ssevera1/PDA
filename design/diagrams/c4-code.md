# C4 Level 4: Code Diagram

Module and class-level detail for the key subsystems.

## LLM Provider Subsystem

```mermaid
classDiagram
    direction TB

    class BaseLLMProvider {
        <<abstract>>
        +generate(messages: list[dict], system: str, max_tokens: int) str*
    }

    class ClaudeProvider {
        -client: anthropic.Anthropic
        -model: str = "claude-sonnet-4-5-20250929"
        +generate(messages, system, max_tokens) str
    }
    note for ClaudeProvider "Uses native Anthropic SDK.\nSystem prompt passed as\nseparate 'system' parameter.\nDefault: claude-sonnet-4-5-20250929"

    class _OpenAICompatibleProvider {
        <<abstract>>
        -client: openai.OpenAI
        -model: str
        +generate(messages, system, max_tokens) str
    }
    note for _OpenAICompatibleProvider "Prepends system prompt as\n{'role': 'system'} message.\nShared OpenAI SDK client."

    class GrokProvider {
        -base_url: "https://api.x.ai/v1"
        -model: str = "grok-3-mini"
    }

    class GeminiProvider {
        -base_url: "https://generativelanguage.googleapis.com/v1beta/openai/"
        -model: str = "gemini-2.5-flash"
    }

    class get_provider {
        <<function>>
        +get_provider() BaseLLMProvider
    }
    note for get_provider "Factory function with\n@lru_cache singleton.\nSelects provider from\nconfig.llm_provider enum."

    BaseLLMProvider <|-- ClaudeProvider
    BaseLLMProvider <|-- _OpenAICompatibleProvider
    _OpenAICompatibleProvider <|-- GrokProvider
    _OpenAICompatibleProvider <|-- GeminiProvider
    get_provider ..> BaseLLMProvider : creates
    get_provider ..> ClaudeProvider : if provider == "claude"
    get_provider ..> GrokProvider : if provider == "grok"
    get_provider ..> GeminiProvider : if provider == "gemini"
```

## Session State Model

```mermaid
classDiagram
    direction LR

    class ConversationStore {
        -_sessions: dict[str, CallSession]
        +create(call_sid, caller, city, state) CallSession
        +get(call_sid) CallSession | None
        +remove(call_sid) None
        +active_count() int
    }
    note for ConversationStore "Singleton instance.\nMax 10 concurrent sessions\nenforced at webhook layer."

    class CallSession {
        +call_sid: str
        +caller: str
        +caller_city: str
        +caller_state: str
        +started_at: datetime
        +messages: list[dict]
        +needs_escalation: bool
        +summary: str | None
        +add_caller_message(text: str) None
        +add_agent_message(text: str) None
        +duration_seconds() int
        +duration_display() str
    }
    note for CallSession "@dataclass with message\nhistory as list of\n{'role': str, 'content': str}\ndicts. Duration computed\nfrom started_at."

    ConversationStore "1" --> "*" CallSession : manages
```

## Conversation Brain

```mermaid
classDiagram
    direction TB

    class brain {
        <<module>>
        +respond(session: CallSession, caller_input: str) tuple[str, bool]
        +generate_greeting(session: CallSession) str
        +summarize_call(session: CallSession) str
    }
    note for brain "respond() returns (reply_text, is_complete).\nis_complete=True when LLM output\ncontains 'CALL_COMPLETE' flag."

    class prompts {
        <<module>>
        +system_prompt() str
        +SUMMARY_PROMPT: str
    }
    note for prompts "system_prompt() injects\nAGENT_NAME and OWNER_NAME\nfrom config. SUMMARY_PROMPT\ndefines structured output format."

    class BaseLLMProvider {
        +generate(messages, system, max_tokens) str
    }

    class CallSession {
        +messages: list[dict]
        +add_caller_message(text) None
        +add_agent_message(text) None
    }

    brain ..> prompts : system_prompt(), SUMMARY_PROMPT
    brain ..> BaseLLMProvider : get_provider().generate()
    brain ..> CallSession : reads/mutates messages
```

## Webhook Request Handler

```mermaid
classDiagram
    direction TB

    class twilio_webhook {
        <<module / FastAPI Router>>
        +router: APIRouter
        -_twiml_response(body: str) Response
        -_say(text: str) str
        -_gather_with_say(text: str) str
        -_sanitize_field(value: str, max_len: int) str
        -_validate_twilio_signature(request, form_data) bool
    }

    class incoming_call {
        <<POST /voice/incoming>>
        +Checks concurrent call limit (max 10)
        +Creates CallSession in store
        +Calls brain.generate_greeting()
        +Returns TwiML: Say greeting + Gather
    }

    class gather_response {
        <<POST /voice/gather>>
        +Validates Twilio signature
        +Retrieves session from store
        +Sanitizes SpeechResult
        +Handles empty speech (re-prompt)
        +Enforces turn limit (max 20)
        +Calls brain.respond()
        +Detects CALL_COMPLETE flag
        +On completion: summarize + notify + cleanup
        +Returns TwiML: Say reply + Gather or Hangup
    }

    class status_callback {
        <<POST /voice/status>>
        +Handles unexpected caller hangups
        +If session exists: summarize + notify + cleanup
        +If no session: 204 No Content
    }

    twilio_webhook --> incoming_call
    twilio_webhook --> gather_response
    twilio_webhook --> status_callback
```

## Notification Pipeline

```mermaid
classDiagram
    direction LR

    class dispatcher {
        <<module>>
        +send_notifications(session: CallSession, summary: str) None
        -_persist_call(session, summary) None
    }
    note for dispatcher "send_notifications() calls\n_persist_call() synchronously,\nthen sends Telegram async.\nEach channel fails independently."

    class telegram {
        <<module>>
        +send_call_summary(session: CallSession, summary: str) None
        +send_urgent_alert(session: CallSession, summary: str) None
        -_send_telegram_sync(message: str) None
    }
    note for telegram "_send_telegram_sync() uses\nurllib.request (no external dep).\n15-second timeout.\nHTML parse_mode."

    class CallSession {
        +caller: str
        +caller_city: str
        +caller_state: str
        +duration_display() str
        +messages: list[dict]
    }

    class call_history_jsonl {
        <<file>>
        JSONL append-only log
    }

    dispatcher ..> call_history_jsonl : _persist_call() with threading.Lock
    dispatcher ..> telegram : send_call_summary()
    dispatcher ..> CallSession : reads session data
    telegram ..> CallSession : reads for formatting
```
