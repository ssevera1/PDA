"""
PDAgent — Personal Digital Agent
A Claude-powered AI assistant that handles your phone calls.
"""

import asyncio
import logging
import os

from contextlib import asynccontextmanager
from fastapi import FastAPI

from telephony.handlers import router as voice_router
from store.conversations import store
from security import (
    TwilioSignatureMiddleware,
    RateLimitMiddleware,
    cleanup_stale_sessions,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-24s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background session cleanup
    task = asyncio.create_task(cleanup_stale_sessions())
    yield
    task.cancel()


# Disable OpenAPI docs in production
is_dev = os.getenv("ENVIRONMENT", "production") == "development"

app = FastAPI(
    title="PDAgent",
    description="Personal Digital Agent — AI-powered call handling",
    version="1.0.0",
    docs_url="/docs" if is_dev else None,
    redoc_url="/redoc" if is_dev else None,
    openapi_url="/openapi.json" if is_dev else None,
    lifespan=lifespan,
)

# Security middleware — order matters (outermost runs first)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(TwilioSignatureMiddleware)

app.include_router(voice_router)


@app.get("/")
async def root():
    return {
        "service": "PDAgent",
        "status": "running",
        "active_calls": store.active_count(),
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
