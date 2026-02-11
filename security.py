"""Security middleware and utilities."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from twilio.request_validator import RequestValidator

from config import get_settings
from store.conversations import store

logger = logging.getLogger("pdagent.security")

# ---------------------------------------------------------------------------
# Twilio Signature Validation
# ---------------------------------------------------------------------------

class TwilioSignatureMiddleware(BaseHTTPMiddleware):
    """Reject any request to /voice/* that doesn't carry a valid Twilio signature."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/voice"):
            return await call_next(request)

        settings = get_settings()
        validator = RequestValidator(settings.twilio_auth_token)

        # Reconstruct the full URL Twilio used (must match exactly)
        url = str(request.url).replace("http://", "https://", 1)

        signature = request.headers.get("X-Twilio-Signature", "")

        # Read and cache the body so downstream handlers can still use it
        body = await request.body()
        # Parse form params for validation
        from urllib.parse import parse_qs
        params = {k: v[0] for k, v in parse_qs(body.decode()).items()}

        if not validator.validate(url, params, signature):
            logger.warning(
                f"Rejected request with invalid Twilio signature: {request.url.path}"
            )
            raise HTTPException(status_code=403, detail="Invalid signature")

        return await call_next(request)


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------

class RateLimiter:
    """Simple in-memory rate limiter using sliding window."""

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self.window
        # Prune old entries
        self._hits[key] = [t for t in self._hits[key] if t > cutoff]
        if len(self._hits[key]) >= self.max_requests:
            return False
        self._hits[key].append(now)
        return True


_limiter = RateLimiter(max_requests=30, window_seconds=60)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limit requests to /voice/* endpoints by caller IP."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/voice"):
            return await call_next(request)

        client_ip = request.headers.get(
            "X-Forwarded-For", request.client.host if request.client else "unknown"
        ).split(",")[0].strip()

        if not _limiter.is_allowed(client_ip):
            logger.warning(f"Rate limited: {client_ip} on {request.url.path}")
            raise HTTPException(status_code=429, detail="Too many requests")

        return await call_next(request)


# ---------------------------------------------------------------------------
# Stale Session Cleanup
# ---------------------------------------------------------------------------

MAX_SESSION_AGE_SECONDS = 3600  # 1 hour — no call should last this long


async def cleanup_stale_sessions():
    """Background task that purges orphaned sessions every 5 minutes."""
    while True:
        await asyncio.sleep(300)
        now = time.time()
        stale = [
            sid
            for sid, session in store._sessions.items()
            if (now - session.started_at) > MAX_SESSION_AGE_SECONDS
        ]
        for sid in stale:
            store.remove(sid)
            logger.info(f"Cleaned up stale session: {sid}")
