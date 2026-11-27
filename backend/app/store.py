"""In-memory run store with event fan-out.

Mutations are synchronous on the event loop, which keeps ledger and dispatch
updates atomic without a lock. Disk checkpoints are layered on top elsewhere.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .checkpoint import load_checkpoints, prune, save_checkpoint
from .models import AgentNode, RunEvent, RunState

logger = logging.getLogger("agent_g.store")

EVENT_KINDS = frozenset(
    {
        "run_created",
        "run_started",
        "run_resumed",
        "run_finished",
        "run_cancelled",
        "run_interrupted",
        "agent_spawned",
        "agent_started",
        "agent_step",
        "agent_finished",
        "agent_failed",
        "agent_cancelled",
        "tool_call",
        "tool_result",
        "invalid_tool_call",
        "artifact_written",
        "artifact_overwrite",
        "review_passed",
        "review_rejected",
        "budget_reserved",
        "budget_settled",
        "budget_refunded",
        "budget_soft_limit",
        "budget_exhausted",
        "provider_fallback",
        "breaker_open",
        "stall_warning",
        "dedupe_skipped",
        "limit_reached",
        "checkpoint_saved",
    }
)

MAX_RETAINED_RUNS = 40
SUBSCRIBER_QUEUE_SIZE = 2000
CHECKPOINT_INTERVAL_S = 2.0
CHECKPOINT_TRIGGER_KINDS = frozenset(
    {
        "run_started",
        "run_resumed",
        "run_finished",
        "run_cancelled",
        "run_interrupted",
        "agent_finished",
        "agent_failed",
        "artifact_written",
        "artifact_overwrite",
        "budget_exhausted",
        "review_passed",
        "review_rejected",
    }
)


class RunStore:
    def __init__(self) -> None:
        self._runs: OrderedDict[str, RunState] = OrderedDict()
        self._state_dir: Path | None = None

    def attach_state_dir(self, state_dir: Path) -> list[RunState]:
        """Load checkpointed runs and persist every later mutation under state_dir."""
        self._state_dir = state_dir
        for run in load_checkpoints(state_dir):
            if run.run_id in self._runs:
                continue
            self._runs[run.run_id] = run
        self._runs = OrderedDict(sorted(self._runs.items(), key=lambda item: item[1].created_at))
        self._evict_if_needed()
        prune(state_dir)
        for run in self._runs.values():
            try:
                save_checkpoint(state_dir, run)
            except OSError:
                logger.warning("could not normalise checkpoint for %s", run.run_id, exc_info=True)
        return list(self._runs.values())

    def create(
        self,
        task: str,
        *,
        budget_tokens: int,
        max_depth: int,
        max_concurrency: int,
    ) -> RunState:
        run_id = uuid.uuid4().hex[:12]
        run = RunState(
            run_id=run_id,
            task=task,
            budget_tokens=budget_tokens,
            max_depth=max_depth,
            max_concurrency=max_concurrency,
        )
        self._runs[run_id] = run
        self._evict_if_needed()
        return run

    def get(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)

    def list_ids(self) -> list[str]:
        return list(self._runs.keys())

    def add_agent(
        self,
        run: RunState,
        *,
        role: str,
        task: str,
        parent_id: str | None,
        depth: int,
    ) -> AgentNode:
        agent = AgentNode(
            id=f"a{len(run.agents) + 1}",
            role=role,
            task=task,
            parent_id=parent_id,
            depth=depth,
        )
        run.agents[agent.id] = agent
        run.agent_order.append(agent.id)
        return agent

    def append(
        self,
        run: RunState,
        kind: str,
        *,
        agent: AgentNode | None = None,
        summary: str = "",
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = 0.0,
        latency_ms: int = 0,
        data: dict[str, Any] | None = None,
    ) -> RunEvent:
        event = self._record(
            run,
            kind,
            agent=agent,
            summary=summary,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            latency_ms=latency_ms,
            data=data,
        )
        self._persist(run, kind)
        return event

    def _record(
        self,
        run: RunState,
        kind: str,
        *,
        agent: AgentNode | None = None,
        summary: str = "",
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = 0.0,
        latency_ms: int = 0,
        data: dict[str, Any] | None = None,
    ) -> RunEvent:
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind: {kind}")
        event = RunEvent(
            id=run.next_event_id,
            ts=time.time(),
            kind=kind,
            agent_id=agent.id if agent else "",
            role=agent.role if agent else "",
            depth=agent.depth if agent else 0,
            parent=agent.parent_id if agent else None,
            summary=summary[:500],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            latency_ms=latency_ms,
            data=data or {},
        )
        run.next_event_id += 1
        run.events.append(event)
        for queue in list(run.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)
        return event

    def _persist(self, run: RunState, kind: str) -> None:
        if self._state_dir is None:
            return
        now = time.time()
        forced = kind in CHECKPOINT_TRIGGER_KINDS
        last = float(run.debug.get("_checkpoint_at", 0.0))
        if not forced and now - last < CHECKPOINT_INTERVAL_S:
            return
        run.debug["_checkpoint_at"] = now
        try:
            save_checkpoint(self._state_dir, run)
        except OSError:
            logger.warning("checkpoint save failed run_id=%s", run.run_id, exc_info=True)
            return
        if forced:
            self._record(
                run,
                "checkpoint_saved",
                summary="run state saved",
                data={"run_id": run.run_id},
            )

    def _evict_if_needed(self) -> None:
        while len(self._runs) > MAX_RETAINED_RUNS:
            for run_id, run in self._runs.items():
                if run.status not in ("queued", "running"):
                    del self._runs[run_id]
                    break
            else:
                break


store = RunStore()