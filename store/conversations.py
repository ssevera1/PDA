from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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

    def __post_init__(self) -> None:
        if not self.call_sid or not isinstance(self.call_sid, str):
            raise ValueError("call_sid must be a non-empty string")
        if not self.caller or not isinstance(self.caller, str):
            raise ValueError("caller must be a non-empty string")

    def add_caller_message(self, text: str) -> None:
        if not text or not isinstance(text, str):
            raise ValueError("message text must be a non-empty string")
        if not isinstance(self.messages, list):
            logger.error(
                f"Message store corrupted for session {self.call_sid}: "
                f"expected list, got {type(self.messages)}"
            )
            raise RuntimeError("Message store state is invalid")
        self.messages.append({"role": "user", "content": text})
        logger.debug(
            f"Added caller message to session {self.call_sid}, "
            f"total messages: {len(self.messages)}"
        )

    def add_agent_message(self, text: str) -> None:
        if not text or not isinstance(text, str):
            raise ValueError("message text must be a non-empty string")
        if not isinstance(self.messages, list):
            logger.error(
                f"Message store corrupted for session {self.call_sid}: "
                f"expected list, got {type(self.messages)}"
            )
            raise RuntimeError("Message store state is invalid")
        self.messages.append({"role": "assistant", "content": text})
        logger.debug(
            f"Added agent message to session {self.call_sid}, "
            f"total messages: {len(self.messages)}"
        )

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
        if not call_sid or not isinstance(call_sid, str):
            raise ValueError("call_sid must be a non-empty string")
        if not caller or not isinstance(caller, str):
            raise ValueError("caller must be a non-empty string")
        if call_sid in self._sessions:
            logger.warning(
                f"Creating session with duplicate call_sid {call_sid}, "
                f"overwriting existing session"
            )
        session = CallSession(call_sid=call_sid, caller=caller, **kwargs)
        self._sessions[call_sid] = session
        logger.info(f"Created session {call_sid} for caller {caller}")
        return session

    def get(self, call_sid: str) -> CallSession | None:
        session = self._sessions.get(call_sid)
        if session is None:
            logger.debug(f"Session {call_sid} not found")
        return session

    def remove(self, call_sid: str) -> CallSession | None:
        session = self._sessions.pop(call_sid, None)
        if session is None:
            logger.warning(f"Attempted to remove non-existent session {call_sid}")
        else:
            logger.info(
                f"Removed session {call_sid}, duration: {session.duration_display}"
            )
        return session

    def active_count(self) -> int:
        return len(self._sessions)


# Singleton
store = ConversationStore()
