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
from .events import stream_run_events, tick_hub
from .llm import LlmClient
from .models import RunState
from .orchestrator import ResumeError, execute_run, prepare_resume
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


class FailureBody(BaseModel):
    mode: str = Field(pattern="^(off|transient|permanent|structural|task)$")
    calls: int | None = Field(default=None, ge=0, le=1000)


class ResumeBody(BaseModel):
    extra_budget_tokens: int | None = Field(default=None, ge=10_000, le=2_000_000)


class DebugBody(BaseModel):
    budget_tokens: int | None = Field(default=None, ge=10_000, le=2_000_000)
    max_depth: int | None = Field(default=None, ge=0, le=3)
    max_concurrency: int | None = Field(default=None, ge=1, le=6)
    fail_next: bool | None = None


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.llm = LlmClient(settings)
    app.state.tasks = set()
    app.state.run_tasks = {}
    recovered = store.attach_state_dir(settings.state_dir)
    logger.info(
        "loaded %s run checkpoints from %s", len(recovered), settings.state_dir
    )
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
def health(request: Request) -> dict[str, object]:
    return {
        "status": "ok",
        "uptime_s": round(time.time() - STARTED_AT, 1),
        "provider": settings.provider.base_url,
        "model_main": settings.provider.model_main,
        "model_sub": settings.provider.model_sub,
        "fallback_configured": settings.fallback is not None,
        "failure_inject_mode": request.app.state.llm.injector.mode,
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
    _launch(request.app, run, resume=False)
    return {"run_id": run.run_id, "status": run.status}


def _launch(app: FastAPI, run: RunState, *, resume: bool) -> None:
    task = asyncio.create_task(execute_run(run, app.state.llm, store, resume=resume))
    app.state.tasks.add(task)
    app.state.run_tasks[run.run_id] = task

    def _done(done: asyncio.Task[None]) -> None:
        app.state.tasks.discard(done)
        if app.state.run_tasks.get(run.run_id) is done:
            app.state.run_tasks.pop(run.run_id, None)
        if not done.cancelled() and done.exception() is not None:
            logger.error("background run failed", exc_info=done.exception())

    task.add_done_callback(_done)


@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str, body: ResumeBody, request: Request) -> dict[str, object]:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    try:
        prepare_resume(run, body.extra_budget_tokens)
    except ResumeError as error:
        raise HTTPException(
            status_code=409, detail={"error": error.code, "detail": error.detail}
        ) from error
    _launch(request.app, run, resume=True)
    logger.info("resume requested run_id=%s budget=%s", run_id, run.budget_tokens)
    return {"run_id": run_id, "status": run.status, "budget_tokens": run.budget_tokens}


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request) -> dict[str, object]:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"run is not active: {run.status}")
    run.cancel_event.set()
    task = request.app.state.run_tasks.get(run_id)
    if task is not None and not task.done():
        task.cancel()
    logger.info("cancel requested run_id=%s", run_id)
    return {"run_id": run_id, "status": "cancelling"}


@app.patch("/api/runs/{run_id}/debug")
def patch_run_debug(run_id: str, body: DebugBody) -> dict[str, object]:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"run is not active: {run.status}")
    if body.budget_tokens is not None:
        run.budget_tokens = body.budget_tokens
    if body.max_depth is not None:
        run.max_depth = body.max_depth
    if body.max_concurrency is not None:
        run.max_concurrency = body.max_concurrency
    if body.fail_next is not None:
        if body.fail_next:
            run.debug["fail_next"] = True
        else:
            run.debug.pop("fail_next", None)
    logger.info(
        "debug patched run_id=%s budget=%s depth=%s concurrency=%s fail_next=%s",
        run_id, run.budget_tokens, run.max_depth, run.max_concurrency, body.fail_next,
    )
    return {
        "ok": True,
        "budget_tokens": run.budget_tokens,
        "max_depth": run.max_depth,
        "max_concurrency": run.max_concurrency,
        "fail_next": bool(run.debug.get("fail_next")),
    }


@app.get("/api/debug/failures")
def get_failure_injection(request: Request) -> dict[str, object]:
    return request.app.state.llm.injector.snapshot()


@app.post("/api/debug/failures")
def set_failure_injection(body: FailureBody, request: Request) -> dict[str, object]:
    request.app.state.llm.injector.configure(body.mode, body.calls)
    snapshot = request.app.state.llm.injector.snapshot()
    logger.warning("failure injection configured %s", snapshot)
    return snapshot


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


@app.get("/api/runs/{run_id}/agents/{agent_id}/conversation")
def get_agent_conversation(run_id: str, agent_id: str) -> dict[str, object]:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    agent = run.agents.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return {
        "agent_id": agent.id,
        "role": agent.role,
        "status": agent.status,
        "task": agent.task,
        "available_tools": agent.available_tools,
        "messages": agent.transcript,
    }


@app.get("/api/runs/{run_id}/events")
def get_run_events(run_id: str) -> dict[str, object]:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"events": [event.public() for event in run.events], "next": run.next_event_id}


@app.get("/api/runs/{run_id}/stream")
async def stream_run(
    run_id: str, request: Request, last_event_id: int | None = None
) -> StreamingResponse:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    raw_last = request.headers.get("last-event-id")
    if raw_last is not None:
        try:
            last_event_id = int(raw_last)
        except ValueError:
            pass
    return StreamingResponse(
        stream_run_events(run, last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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