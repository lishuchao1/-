from __future__ import annotations

import contextlib
import time
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .config import settings
from .events import tick_hub

STARTED_AT = time.time()


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await tick_hub.stop()


app = FastAPI(title="Super-Agent Orchestration Demo", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "uptime_s": round(time.time() - STARTED_AT, 1),
        "provider": settings.provider.base_url,
        "model_main": settings.provider.model_main,
        "model_sub": settings.provider.model_sub,
        "fallback_configured": settings.fallback is not None,
    }


@app.get("/api/tick")
async def tick(request: Request, last_event_id: int | None = None) -> StreamingResponse:
    raw_last = request.headers.get("last-event-id")
    if raw_last is not None:
        try:
            last_event_id = int(raw_last)
        except ValueError:
            pass
    return StreamingResponse(
        tick_hub.stream(last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )