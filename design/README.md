# PDAgent Design Documentation

This directory contains architectural documentation for PDAgent, an AI-powered personal phone assistant.

## Contents

### `diagrams/`

C4 Model architecture diagrams rendered in Mermaid.js:

| File | Level | Description |
|------|-------|-------------|
| [c4-context.md](diagrams/c4-context.md) | L1 - System Context | PDAgent in relation to users and external systems |
| [c4-container.md](diagrams/c4-container.md) | L2 - Container | Internal containers and their responsibilities |
| [c4-component.md](diagrams/c4-component.md) | L3 - Component | Components within the PDAgent application |
| [c4-code.md](diagrams/c4-code.md) | L4 - Code | Class/module-level detail for key subsystems |
| [data-flow.md](diagrams/data-flow.md) | Supplementary | End-to-end data flow and latency analysis |

### `adrs/`

Architecture Decision Records documenting key design choices:

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](adrs/ADR-001-in-memory-session-store.md) | In-memory session store over external database | Accepted |
| [ADR-002](adrs/ADR-002-multi-provider-llm-abstraction.md) | Multi-provider LLM abstraction layer | Accepted |
| [ADR-003](adrs/ADR-003-twiml-webhook-over-websocket.md) | TwiML webhook pattern over WebSocket/WebRTC | Accepted |
| [ADR-004](adrs/ADR-004-jsonl-file-persistence.md) | JSONL file persistence over database | Accepted |
| [ADR-005](adrs/ADR-005-telegram-notifications.md) | Telegram for real-time call notifications | Accepted |
| [ADR-006](adrs/ADR-006-call-complete-flag-pattern.md) | CALL_COMPLETE flag for conversation termination | Accepted |
| [ADR-007](adrs/ADR-007-rate-limiting-and-security.md) | Layered security middleware architecture | Accepted |
| [ADR-008](adrs/ADR-008-polly-neural-voice.md) | Amazon Polly Neural voice for TTS | Accepted |

## Rendering Diagrams

All diagrams use [Mermaid.js](https://mermaid.js.org/) syntax. They render natively on GitHub, GitLab, and in editors with Mermaid support (VS Code with Markdown Preview Mermaid extension, Obsidian, etc.).

To render locally:

```bash
npx @mermaid-js/mermaid-cli mmdc -i diagrams/c4-context.md -o output.svg
```

## ADR Format

Each ADR follows the standard format:

- **Status**: Proposed | Accepted | Deprecated | Superseded
- **Context**: The situation and forces at play
- **Decision**: What was decided
- **Consequences**: Trade-offs accepted, both positive and negative
