from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import settings
from .events import tick_hub
from .llm import LlmClient
from .orchestrator import execute_run
from .store import store

logger = logging.getLogger("agent_g.api")

STARTED_AT = time.time()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


class CreateRunBody(BaseModel):
    task: str = Field(min_length=4, max_length=4000)
    budget_tokens: int | None = Field(default=None, ge=10_000, le=2_000_000)
    max_depth: int | None = Field(default=None, ge=0, le=3)
    max_concurrency: int | None = Field(default=None, ge=1, le=6)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.llm = LlmClient(settings)
    app.state.tasks = set()
    try:
        yield
    finally:
        for task in list(app.state.tasks):
            task.cancel()
        for task in list(app.state.tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await app.state.llm.aclose()
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


@app.post("/api/runs")
async def create_run(body: CreateRunBody, request: Request) -> dict[str, object]:
    run = store.create(
        body.task.strip(),
        budget_tokens=body.budget_tokens or settings.budget_tokens,
        max_depth=settings.max_depth if body.max_depth is None else body.max_depth,
        max_concurrency=(
            settings.max_concurrency if body.max_concurrency is None else body.max_concurrency
        ),
    )
    background = asyncio.create_task(execute_run(run, request.app.state.llm, store))
    request.app.state.tasks.add(background)

    def _done(task: asyncio.Task[None]) -> None:
        request.app.state.tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("background run failed", exc_info=task.exception())

    background.add_done_callback(_done)
    return {"run_id": run.run_id, "status": run.status}


@app.get("/api/runs")
def list_runs() -> dict[str, object]:
    items = []
    for run_id in reversed(store.list_ids()):
        run = store.get(run_id)
        if run is None:
            continue
        items.append(
            {
                "run_id": run.run_id,
                "task": run.task[:120],
                "status": run.status,
                "tokens_used": run.tokens_used,
                "cost": round(run.cost, 8),
                "agents": len(run.agents),
                "created_at": round(run.created_at, 3),
            }
        )
    return {"runs": items}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, object]:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run.public()


@app.get("/api/runs/{run_id}/events")
def get_run_events(run_id: str) -> dict[str, object]:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"events": [event.public() for event in run.events], "next": run.next_event_id}


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