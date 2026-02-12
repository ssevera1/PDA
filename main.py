"""
PDAgent — Personal Digital Agent
An AI-powered personal assistant you talk to through your browser.
"""

import asyncio
import logging
import os

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from voice.websocket import router as ws_router
from voice.stt import router as stt_router
from voice.tts import router as tts_router
from notifications.dashboard import router as dashboard_router
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
    version="2.0.0",
    docs_url="/docs" if is_dev else None,
    redoc_url="/redoc" if is_dev else None,
    openapi_url="/openapi.json" if is_dev else None,
    lifespan=lifespan,
)

# Security middleware — order matters (outermost runs first)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# Routers
app.include_router(ws_router)
app.include_router(stt_router)
app.include_router(tts_router)
app.include_router(dashboard_router)

# Static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    return {
        "service": "PDAgent",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/call")
async def call_page():
    return FileResponse(str(static_dir / "call.html"))


@app.get("/dashboard")
async def dashboard_page():
    return FileResponse(str(static_dir / "dashboard.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
