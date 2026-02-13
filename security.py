"""Security middleware and utilities."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from store.conversations import store

logger = logging.getLogger("pdagent.security")


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
        hits = [t for t in self._hits.get(key, []) if t > cutoff]
        # Clean up empty keys to prevent memory leak
        if not hits:
            self._hits.pop(key, None)
            hits = []
        if len(hits) >= self.max_requests:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True


_limiter = RateLimiter(max_requests=30, window_seconds=60)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limit requests to /voice/* endpoints by caller IP."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/voice"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        if not _limiter.is_allowed(client_ip):
            logger.warning(f"Rate limited: {client_ip} on {path}")
            raise HTTPException(status_code=429, detail="Too many requests")

        return await call_next(request)


# ---------------------------------------------------------------------------
# Security Headers Middleware
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'"
        )
        return response


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
            for sid, session in list(store._sessions.items())
            if (now - session.started_at) > MAX_SESSION_AGE_SECONDS
        ]
        for sid in stale:
            store.remove(sid)
            logger.info(f"Cleaned up stale session: {sid}")
