"""Run event stream: snapshot + replay + live without duplicated ids (T18)."""

from __future__ import annotations

import asyncio
import json

from app.events import stream_run_events
from app.store import RunStore


def parse(frame: str) -> dict[str, object] | None:
    if frame.startswith(":"):
        return None
    fields: dict[str, str] = {}
    for line in frame.strip().splitlines():
        key, _, value = line.partition(": ")
        fields[key] = value
    return {
        "id": int(fields["id"]),
        "event": fields["event"],
        "data": json.loads(fields["data"]),
    }


async def collect(run, last_event_id: int | None) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    async for frame in stream_run_events(run, last_event_id):
        parsed = parse(frame)
        if parsed is not None:
            frames.append(parsed)
    return frames


def make_run(store: RunStore):
    return store.create(
        "stream test", budget_tokens=100_000, max_depth=2, max_concurrency=2
    )


async def test_replay_after_last_event_id_has_no_duplicates() -> None:
    store = RunStore()
    run = make_run(store)
    for index in range(5):
        store.append(run, "agent_step", summary=f"step {index}")
    run.status = "done"
    frames = await collect(run, 2)

    snapshots = [frame for frame in frames if frame["event"] == "snapshot"]
    events = [frame for frame in frames if frame["event"] == "run_event"]
    assert len(snapshots) == 2
    assert snapshots[0]["id"] == 2
    assert snapshots[-1]["data"]["status"] == "done"
    assert [frame["id"] for frame in events] == [3, 4, 5]
    ids = [frame["id"] for frame in events]
    assert len(ids) == len(set(ids))


async def test_terminal_run_closes_after_final_snapshot() -> None:
    store = RunStore()
    run = make_run(store)
    store.append(run, "agent_step", summary="only step")
    run.status = "failed"
    frames = await collect(run, None)
    assert frames[-1]["event"] == "snapshot"
    assert frames[-1]["data"]["status"] == "failed"
    assert [frame["id"] for frame in frames if frame["event"] == "run_event"] == [1]


async def test_live_tail_delivers_new_events_once() -> None:
    store = RunStore()
    run = make_run(store)
    store.append(run, "agent_step", summary="before connect")

    frames: list[dict[str, object]] = []

    async def consume() -> None:
        async for frame in stream_run_events(run, 1):
            parsed = parse(frame)
            if parsed is not None:
                frames.append(parsed)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    store.append(run, "agent_step", summary="live one")
    store.append(run, "agent_step", summary="live two")
    run.status = "done"
    store.append(run, "run_finished", summary="status=done")
    await asyncio.wait_for(task, timeout=2)

    events = [frame for frame in frames if frame["event"] == "run_event"]
    assert [frame["id"] for frame in events] == [2, 3, 4]
    assert frames[-1]["event"] == "snapshot"
    assert frames[-1]["data"]["status"] == "done"


async def test_subscriber_is_removed_after_close() -> None:
    store = RunStore()
    run = make_run(store)
    run.status = "done"
    await collect(run, None)
    assert run.subscribers == set()