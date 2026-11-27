"""Server-sent event hub used by the tick demo endpoint.

A single background producer appends ticks to a ring buffer and fans them
out to every subscriber queue. New subscribers replay buffered ticks after
their Last-Event-ID so a dropped connection resumes without gaps.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import deque
from collections.abc import AsyncIterator

from .models import RunEvent, RunState

TICK_INTERVAL_S = 1.0
BUFFER_SIZE = 600
RUN_STREAM_PING_S = 10.0
TERMINAL_RUN_STATUSES = ("done", "failed", "cancelled", "interrupted", "budget_exhausted")


def format_sse(event_id: int, event: str, payload: dict[str, object]) -> str:
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


class TickHub:
    def __init__(self) -> None:
        self._events: deque[tuple[int, dict[str, object]]] = deque(maxlen=BUFFER_SIZE)
        self._subscribers: set[asyncio.Queue[tuple[int, dict[str, object]] | None]] = set()
        self._task: asyncio.Task[None] | None = None
        self._seq = 0
        self._started_at = time.time()

    def _ensure_running(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._produce())

    async def _produce(self) -> None:
        while True:
            await asyncio.sleep(TICK_INTERVAL_S)
            self._seq += 1
            event = {
                "seq": self._seq,
                "ts": round(time.time(), 3),
                "uptime_s": round(time.time() - self._started_at, 1),
            }
            self._events.append((self._seq, event))
            for queue in list(self._subscribers):
                queue.put_nowait((self._seq, event))

    async def stream(self, last_event_id: int | None) -> AsyncIterator[str]:
        self._ensure_running()
        queue: asyncio.Queue[tuple[int, dict[str, object]] | None] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            yield ": connected\n\n"
            replay_from = last_event_id or 0
            replayed = [item for item in self._events if item[0] > replay_from]
            for event_id, payload in replayed:
                yield format_sse(event_id, "tick", {**payload, "replayed": True})
            newest = replay_from
            while True:
                item = await queue.get()
                if item is None:
                    break
                event_id, payload = item
                if event_id <= newest:
                    continue
                newest = event_id
                yield format_sse(event_id, "tick", payload)
        finally:
            self._subscribers.discard(queue)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


tick_hub = TickHub()


async def stream_run_events(run: RunState, last_event_id: int | None) -> AsyncIterator[str]:
    """Snapshot first, then replay missed events and follow live ones.

    The snapshot always reflects the full current state, so a client that
    missed events can rebuild without relying on deltas alone.
    """
    queue: asyncio.Queue[RunEvent] = asyncio.Queue(maxsize=2000)
    run.subscribers.add(queue)
    try:
        yield ": connected\n\n"
        newest = last_event_id or 0
        yield format_sse(newest, "snapshot", run.public())
        for event in list(run.events):
            if event.id <= newest:
                continue
            newest = event.id
            yield format_sse(event.id, "run_event", event.public())
        if run.status in TERMINAL_RUN_STATUSES:
            yield format_sse(newest, "snapshot", run.public())
            return
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=RUN_STREAM_PING_S)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                if run.status in TERMINAL_RUN_STATUSES:
                    yield format_sse(newest, "snapshot", run.public())
                    return
                continue
            if event.id <= newest:
                continue
            newest = event.id
            yield format_sse(event.id, "run_event", event.public())
            if event.kind == "run_finished":
                yield format_sse(newest, "snapshot", run.public())
                return
    finally:
        run.subscribers.discard(queue)