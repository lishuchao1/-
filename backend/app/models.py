"""Run and agent state shared by the orchestrator, the API and the frontend."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

AGENT_STATUSES = (
    "queued",
    "running",
    "done",
    "partial",
    "failed",
    "cancelled",
    "config_error",
)

RUN_STATUSES = (
    "queued",
    "running",
    "done",
    "budget_exhausted",
    "cancelled",
    "failed",
    "interrupted",
)


@dataclass
class RunFlags:
    unverified: bool = False
    tokens_may_be_underreported: bool = False
    thinking_replay_broken: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "unverified": self.unverified,
            "tokens_may_be_underreported": self.tokens_may_be_underreported,
            "thinking_replay_broken": self.thinking_replay_broken,
        }


@dataclass
class AgentNode:
    id: str
    role: str
    task: str
    parent_id: str | None
    depth: int
    status: str = "queued"
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    steps: int = 0
    summary: str = ""
    error_kind: str = ""
    artifact_keys: list[str] = field(default_factory=list)
    available_tools: list[str] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "task": self.task,
            "parent_id": self.parent_id,
            "depth": self.depth,
            "status": self.status,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost": round(self.cost, 8),
            "latency_ms": self.latency_ms,
            "steps": self.steps,
            "summary": self.summary,
            "error_kind": self.error_kind,
            "artifact_keys": list(self.artifact_keys),
            "available_tools": list(self.available_tools),
        }

    def checkpoint(self) -> dict[str, Any]:
        data = self.public()
        data["transcript"] = self.transcript
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AgentNode":
        return cls(
            id=str(raw.get("id", "")),
            role=str(raw.get("role", "")),
            task=str(raw.get("task", "")),
            parent_id=raw.get("parent_id"),
            depth=int(raw.get("depth", 0)),
            status=str(raw.get("status", "queued")),
            tokens_in=int(raw.get("tokens_in", 0)),
            tokens_out=int(raw.get("tokens_out", 0)),
            cost=float(raw.get("cost", 0.0)),
            latency_ms=int(raw.get("latency_ms", 0)),
            steps=int(raw.get("steps", 0)),
            summary=str(raw.get("summary", "")),
            error_kind=str(raw.get("error_kind", "")),
            artifact_keys=list(raw.get("artifact_keys") or []),
            available_tools=list(raw.get("available_tools") or []),
            transcript=list(raw.get("transcript") or []),
        )


@dataclass
class RunEvent:
    id: int
    ts: float
    kind: str
    agent_id: str = ""
    role: str = ""
    depth: int = 0
    parent: str | None = None
    summary: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    data: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": round(self.ts, 3),
            "kind": self.kind,
            "agent_id": self.agent_id,
            "role": self.role,
            "depth": self.depth,
            "parent": self.parent,
            "summary": self.summary,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost": round(self.cost, 8),
            "latency_ms": self.latency_ms,
            "data": self.data,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.public()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RunEvent":
        return cls(
            id=int(raw.get("id", 0)),
            ts=float(raw.get("ts", 0.0)),
            kind=str(raw.get("kind", "")),
            agent_id=str(raw.get("agent_id", "")),
            role=str(raw.get("role", "")),
            depth=int(raw.get("depth", 0)),
            parent=raw.get("parent"),
            summary=str(raw.get("summary", "")),
            tokens_in=int(raw.get("tokens_in", 0)),
            tokens_out=int(raw.get("tokens_out", 0)),
            cost=float(raw.get("cost", 0.0)),
            latency_ms=int(raw.get("latency_ms", 0)),
            data=dict(raw.get("data") or {}),
        )


@dataclass
class RunState:
    run_id: str
    task: str
    budget_tokens: int
    max_depth: int
    max_concurrency: int
    status: str = "queued"
    tokens_used: int = 0
    reserved_tokens: int = 0
    cost: float = 0.0
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None
    agents: dict[str, AgentNode] = field(default_factory=dict)
    agent_order: list[str] = field(default_factory=list)
    events: list[RunEvent] = field(default_factory=list)
    next_event_id: int = 1
    final_answer: str = ""
    slots: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifact_contents: dict[str, str] = field(default_factory=dict, repr=False)
    reservations: dict[str, int] = field(default_factory=dict)
    budget_soft_reported: bool = False
    budget_hard_stop: bool = False
    flags: RunFlags = field(default_factory=RunFlags)
    debug: dict[str, Any] = field(default_factory=dict)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    subscribers: set[asyncio.Queue[RunEvent]] = field(default_factory=set, repr=False)

    @property
    def elapsed_s(self) -> float:
        end = self.ended_at or time.time()
        start = self.started_at or self.created_at
        return round(max(0.0, end - start), 1)

    def agent_list(self) -> list[AgentNode]:
        return [self.agents[agent_id] for agent_id in self.agent_order if agent_id in self.agents]

    def slot_list(self) -> list[dict[str, Any]]:
        return list(self.slots.values())

    def public(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task": self.task,
            "status": self.status,
            "budget_tokens": self.budget_tokens,
            "tokens_used": self.tokens_used,
            "reserved_tokens": self.reserved_tokens,
            "cost": round(self.cost, 8),
            "elapsed_s": self.elapsed_s,
            "max_depth": self.max_depth,
            "max_concurrency": self.max_concurrency,
            **self.flags.to_dict(),
            "agents": [agent.public() for agent in self.agent_list()],
            "slots": self.slot_list(),
            "final_answer": self.final_answer,
            "budget_hard_stop": self.budget_hard_stop,
            "debug": {key: value for key, value in self.debug.items() if not key.startswith("_")},
        }

    def to_checkpoint(self) -> dict[str, Any]:
        return {
            "version": 1,
            "run_id": self.run_id,
            "task": self.task,
            "budget_tokens": self.budget_tokens,
            "max_depth": self.max_depth,
            "max_concurrency": self.max_concurrency,
            "status": self.status,
            "tokens_used": self.tokens_used,
            "reserved_tokens": self.reserved_tokens,
            "cost": self.cost,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "agents": [agent.checkpoint() for agent in self.agent_list()],
            "events": [event.to_dict() for event in self.events],
            "next_event_id": self.next_event_id,
            "final_answer": self.final_answer,
            "slots": self.slots,
            "artifact_contents": self.artifact_contents,
            "reservations": self.reservations,
            "budget_soft_reported": self.budget_soft_reported,
            "budget_hard_stop": self.budget_hard_stop,
            "flags": self.flags.to_dict(),
            "debug": {key: value for key, value in self.debug.items() if not key.startswith("_")},
        }

    @classmethod
    def from_checkpoint(cls, raw: dict[str, Any]) -> "RunState":
        run = cls(
            run_id=str(raw.get("run_id", "")),
            task=str(raw.get("task", "")),
            budget_tokens=int(raw.get("budget_tokens", 0)),
            max_depth=int(raw.get("max_depth", 0)),
            max_concurrency=int(raw.get("max_concurrency", 1)),
            status=str(raw.get("status", "queued")),
            tokens_used=int(raw.get("tokens_used", 0)),
            reserved_tokens=int(raw.get("reserved_tokens", 0)),
            cost=float(raw.get("cost", 0.0)),
            created_at=float(raw.get("created_at", time.time())),
            started_at=raw.get("started_at"),
            ended_at=raw.get("ended_at"),
            next_event_id=int(raw.get("next_event_id", 1)),
            final_answer=str(raw.get("final_answer", "")),
            slots=dict(raw.get("slots") or {}),
            artifact_contents=dict(raw.get("artifact_contents") or {}),
            reservations={key: int(value) for key, value in (raw.get("reservations") or {}).items()},
            budget_soft_reported=bool(raw.get("budget_soft_reported", False)),
            budget_hard_stop=bool(raw.get("budget_hard_stop", False)),
            flags=RunFlags(**(raw.get("flags") or {})),
            debug=dict(raw.get("debug") or {}),
        )
        for item in raw.get("agents") or []:
            agent = AgentNode.from_dict(item)
            run.agents[agent.id] = agent
            run.agent_order.append(agent.id)
        run.events = [RunEvent.from_dict(item) for item in raw.get("events") or []]
        return run