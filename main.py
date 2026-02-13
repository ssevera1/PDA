"""
PDAgent — Personal Digital Agent
An AI-powered personal assistant that handles phone calls via Twilio.
"""

import asyncio
import logging
import os

from contextlib import asynccontextmanager

from fastapi import FastAPI

from voice.twilio_webhook import router as twilio_router
from store.conversations import store
from config import get_settings
from security import (
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    cleanup_stale_sessions,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-24s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure data directory exists
    settings = get_settings()
    os.makedirs(settings.data_dir, exist_ok=True)
    # Start background session cleanup
    task = asyncio.create_task(cleanup_stale_sessions())
    yield
    task.cancel()


# Disable OpenAPI docs in production
is_dev = os.getenv("ENVIRONMENT", "production") == "development"

app = FastAPI(
    title="PDAgent",
    description="Personal Digital Agent — AI-powered call handling",
    version="3.0.0",
    docs_url="/docs" if is_dev else None,
    redoc_url="/redoc" if is_dev else None,
    openapi_url="/openapi.json" if is_dev else None,
    lifespan=lifespan,
)

# Security middleware — order matters (outermost runs first)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# Routers
app.include_router(twilio_router)


@app.get("/")
async def root():
    return {
        "service": "PDAgent",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
