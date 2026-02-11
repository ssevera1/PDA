from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class CallSession:
    call_sid: str
    caller: str
    caller_city: str | None = None
    caller_state: str | None = None
    started_at: float = field(default_factory=time.time)
    messages: list[dict[str, str]] = field(default_factory=list)
    needs_escalation: bool = False
    summary: str | None = None

    def add_caller_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_agent_message(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})

    @property
    def duration_seconds(self) -> float:
        return time.time() - self.started_at

    @property
    def duration_display(self) -> str:
        s = int(self.duration_seconds)
        m, s = divmod(s, 60)
        return f"{m}m {s}s"


class ConversationStore:
    """Thread-safe in-memory store for active call sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, CallSession] = {}

    def create(self, call_sid: str, caller: str, **kwargs) -> CallSession:
        session = CallSession(call_sid=call_sid, caller=caller, **kwargs)
        self._sessions[call_sid] = session
        return session

    def get(self, call_sid: str) -> CallSession | None:
        return self._sessions.get(call_sid)

    def remove(self, call_sid: str) -> CallSession | None:
        return self._sessions.pop(call_sid, None)

    def active_count(self) -> int:
        return len(self._sessions)


# Singleton
store = ConversationStore()
