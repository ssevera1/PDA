"""Single-use tokens tying a media-stream WebSocket to a signature-checked call.

``/voice/incoming`` is Twilio-signature-validated, but a bare WebSocket URL is
not — anyone who guessed it could attach a bridge. So the webhook mints a
token per call, embeds it in the ``<Stream>`` URL, and the WebSocket endpoint
consumes it on connect: unknown, reused, or expired tokens are refused.
In-memory on purpose (single process, 60-second lifetime).
"""

from __future__ import annotations

import secrets
import threading
import time

_TTL_SECONDS = 60
_lock = threading.Lock()
_tokens: dict[str, tuple[str, float]] = {}  # token -> (call_sid, expires_at)


def mint(call_sid: str, *, now: float | None = None) -> str:
    token = secrets.token_urlsafe(24)
    ts = now if now is not None else time.time()
    with _lock:
        # Opportunistic cleanup keeps the dict from growing under abuse.
        expired = [t for t, (_, exp) in _tokens.items() if exp < ts]
        for t in expired:
            del _tokens[t]
        _tokens[token] = (call_sid, ts + _TTL_SECONDS)
    return token


def consume(token: str | None, call_sid: str, *, now: float | None = None) -> bool:
    """True exactly once per minted token, and only for its own call."""
    if not token:
        return False
    ts = now if now is not None else time.time()
    with _lock:
        entry = _tokens.pop(token, None)
    if entry is None:
        return False
    sid, expires_at = entry
    return sid == call_sid and ts <= expires_at
