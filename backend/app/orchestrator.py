"""Supervisor-driven orchestration.

The supervisor plans at runtime through tool calls; there is no hardcoded
pipeline. Sub-agents run with isolated context and return only a summary plus
artifact keys, so the parent sees evidence rather than raw transcripts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from .artifacts import ArtifactError, read_artifact, required_slots, verdict_of, write_artifact
from .config import settings
from .llm import LlmClient, LlmError
from .models import AgentNode, RunState
from .prompts import ROLE_PROMPTS, SUPERVISOR_PROMPT, worker_user_message
from .store import RunStore
from .tool_loop import StepRecord, ToolSpec, run_tool_loop

logger = logging.getLogger("agent_g.orchestrator")

MAX_SUPERVISOR_STEPS = 10
MAX_WORKER_STEPS = 6
MAX_WORKERS = 12
MAX_SUMMARY_CHARS = 600

SPAWN_SCHEMA = {
    "type": "function",
    "function": {
        "name": "spawn_agent",
        "description": "Spawn one specialist sub-agent in an isolated context and wait for its result.",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "enum": ["writer", "marketing", "reviewer"]},
                "task": {"type": "string", "description": "A concrete assignment for the specialist."},
                "context": {
                    "type": "string",
                    "description": "Optional facts the specialist needs; it cannot see your transcript.",
                },
            },
            "required": ["role", "task"],
        },
    },
}

READ_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_artifact",
        "description": "Read an artifact written by a specialist.",
        "parameters": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
}

WRITE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_artifact",
        "description": "Write an artifact under your own role prefix.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "role.slot, lowercase"},
                "content": {"type": "string"},
            },
            "required": ["key", "content"],
        },
    },
}

FINISH_SUPERVISOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": "Finish the run with the final answer for the user.",
        "parameters": {
            "type": "object",
            "properties": {"final_answer": {"type": "string"}},
            "required": ["final_answer"],
        },
    },
}

FINISH_WORKER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": "Finish your assignment with a short summary of what you produced.",
        "parameters": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
}


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "..."


class RunExecutor:
    def __init__(self, run: RunState, client: LlmClient, store: RunStore):
        self.run = run
        self.client = client
        self.store = store
        self.final_answer = ""
        self.worker_summaries: dict[str, str] = {}

    async def execute(self) -> None:
        run = self.run
        run.status = "running"
        run.started_at = time.time()
        self.store.append(run, "run_started", summary=_clip(run.task, 120))
        root = self.store.add_agent(run, role="supervisor", task=run.task, parent_id=None, depth=0)
        try:
            await self._supervise(root)
            run.status = "done" if run.final_answer else "failed"
        except LlmError as error:
            run.status = "failed"
            run.final_answer = f"run failed: {error.kind}: {_clip(str(error), 300)}"
            root.status = "config_error" if error.kind in ("structural_400", "auth") else "failed"
            if error.kind == "structural_400" and "reasoning" in str(error).lower():
                run.flags.thinking_replay_broken = True
            self.store.append(
                run,
                "agent_failed",
                agent=root,
                summary=f"{error.kind}: {_clip(str(error), 200)}",
                data={"kind": error.kind, "status": error.status},
            )
        except asyncio.CancelledError:
            run.status = "cancelled"
            root.status = "cancelled"
            self.store.append(run, "run_cancelled", agent=root, summary="cancelled")
            raise
        except Exception as exc:  # defensive: never leave a run stuck in running
            logger.exception("run crashed")
            run.status = "failed"
            root.status = "failed"
            run.final_answer = f"run failed: internal error: {_clip(str(exc), 300)}"
            self.store.append(run, "agent_failed", agent=root, summary=_clip(str(exc), 200))
        finally:
            run.ended_at = time.time()
            if root.status == "running":
                root.status = "done" if self.final_answer else "partial"
            self.store.append(
                run,
                "run_finished",
                agent=root,
                summary=f"status={run.status} tokens={run.tokens_used} cost={run.cost:.6f}",
                data={"status": run.status, "elapsed_s": run.elapsed_s},
            )

    async def _supervise(self, root: AgentNode) -> None:
        run = self.run
        root.status = "running"
        self.store.append(run, "agent_started", agent=root, summary="supervisor started")

        def finish_handler(args: dict[str, Any]) -> dict[str, Any]:
            self.final_answer = str(args.get("final_answer", "")).strip()
            return {"ok": True, "received_chars": len(self.final_answer)}

        def read_handler(args: dict[str, Any]) -> dict[str, Any]:
            try:
                content = read_artifact(run, str(args.get("key", "")))
            except ArtifactError as error:
                return {"error": error.code, "detail": error.detail}
            return {"key": args.get("key", ""), "content": content}

        async def spawn_handler(args: dict[str, Any]) -> dict[str, Any]:
            return await self._spawn(root, args)

        tools: dict[str, ToolSpec] = {
            "spawn_agent": ToolSpec(SPAWN_SCHEMA, spawn_handler),
            "read_artifact": ToolSpec(READ_SCHEMA, read_handler),
            "finish": ToolSpec(FINISH_SUPERVISOR_SCHEMA, finish_handler),
        }
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SUPERVISOR_PROMPT},
            {"role": "user", "content": run.task},
        ]
        result = await run_tool_loop(
            self.client,
            role="main",
            messages=messages,
            tools=tools,
            max_steps=MAX_SUPERVISOR_STEPS,
            max_tokens=2000,
            terminal_tools=frozenset({"finish"}),
            on_step=lambda step: self._on_supervisor_step(root, step),
            on_tool=lambda name, args, payload, invalid: self._on_tool(root, name, args, payload, invalid),
        )
        self._account(root, result)

        missing = [name for name, present in required_slots(run).items() if not present]
        if missing:
            run.flags.unverified = True
            self.store.append(
                run,
                "agent_finished",
                agent=root,
                summary=f"missing slots: {', '.join(missing)}",
                data={"missing_slots": missing},
            )
        if verdict_of(run) == "REJECT":
            run.flags.unverified = True
        if not self.final_answer:
            self.final_answer = _clip(result.content, 2000)
            if result.stop_reason != "finished_tool":
                run.flags.unverified = True
        run.final_answer = self.final_answer
        root.status = "done"
        self.store.append(
            run,
            "agent_finished",
            agent=root,
            summary=_clip(self.final_answer, 200),
            tokens_in=root.tokens_in,
            tokens_out=root.tokens_out,
            cost=root.cost,
        )

    def _on_supervisor_step(self, root: AgentNode, step: StepRecord) -> None:
        root.steps += 1
        self.store.append(
            self.run,
            "agent_step",
            agent=root,
            summary=_clip(step.content, 160) or ", ".join(tool["name"] for tool in step.tools),
            tokens_in=step.tokens_in,
            tokens_out=step.tokens_out,
            latency_ms=step.latency_ms,
        )

    def _on_tool(
        self,
        agent: AgentNode,
        name: str,
        arguments: str,
        payload: dict[str, Any],
        invalid: str,
    ) -> None:
        run = self.run
        self.store.append(
            run,
            "tool_call",
            agent=agent,
            summary=f"{name} {_clip(arguments, 160)}",
            data={"name": name, "arguments": _clip(arguments, 400)},
        )
        if invalid:
            self.store.append(
                run,
                "invalid_tool_call",
                agent=agent,
                summary=f"{name}: {invalid}",
                data={"name": name, "reason": invalid},
            )
        self.store.append(
            run,
            "tool_result",
            agent=agent,
            summary=_clip(json.dumps(payload, ensure_ascii=False), 240),
            data={"name": name},
        )

    def _account(self, agent: AgentNode, result: Any) -> None:
        agent.tokens_in += result.usage.tokens_in
        agent.tokens_out += result.usage.tokens_out
        agent.cost = round(agent.cost + result.usage.cost, 8)
        self.run.tokens_used += result.usage.tokens_in + result.usage.tokens_out
        self.run.cost = round(self.run.cost + result.usage.cost, 8)

    async def _spawn(self, parent: AgentNode, args: dict[str, Any]) -> dict[str, Any]:
        run = self.run
        role = str(args.get("role", "")).strip()
        task = str(args.get("task", "")).strip()
        context = str(args.get("context", "") or "")[: settings.context_max_chars]

        if role not in ROLE_PROMPTS:
            return {"error": "invalid_role", "detail": f"role must be one of {sorted(ROLE_PROMPTS)}"}
        if not task:
            return {"error": "invalid_task", "detail": "task must not be empty"}
        if parent.depth >= run.max_depth:
            self.store.append(
                run, "limit_reached", agent=parent, summary=f"depth cap {run.max_depth}",
                data={"limit": "depth", "depth": parent.depth},
            )
            return {"error": "depth_cap", "detail": f"max depth {run.max_depth} reached"}
        workers = [agent for agent in run.agents.values() if agent.role != "supervisor"]
        if len(workers) >= MAX_WORKERS:
            self.store.append(
                run, "limit_reached", agent=parent, summary=f"agent cap {MAX_WORKERS}",
                data={"limit": "agents", "count": len(workers)},
            )
            return {"error": "agent_cap", "detail": f"max {MAX_WORKERS} sub-agents per run"}

        child = self.store.add_agent(
            run, role=role, task=task, parent_id=parent.id, depth=parent.depth + 1
        )
        self.store.append(
            run, "agent_spawned", agent=child, summary=_clip(task, 160),
            data={"role": role, "parent": parent.id},
        )
        return await self._run_worker(child, context)

    async def _run_worker(self, agent: AgentNode, context: str) -> dict[str, Any]:
        run = self.run
        agent.status = "running"
        started = time.perf_counter()
        self.store.append(run, "agent_started", agent=agent, summary=agent.role)
        summary_box: dict[str, str] = {}

        def write_handler(args: dict[str, Any]) -> dict[str, Any]:
            try:
                return write_artifact(
                    self.store, run, agent, str(args.get("key", "")), str(args.get("content", ""))
                )
            except ArtifactError as error:
                return {"error": error.code, "detail": error.detail}

        def read_handler(args: dict[str, Any]) -> dict[str, Any]:
            try:
                return {"key": args.get("key", ""), "content": read_artifact(run, str(args.get("key", "")))}
            except ArtifactError as error:
                return {"error": error.code, "detail": error.detail}

        def finish_handler(args: dict[str, Any]) -> dict[str, Any]:
            summary_box["summary"] = str(args.get("summary", "")).strip()
            return {"ok": True}

        async def spawn_handler(args: dict[str, Any]) -> dict[str, Any]:
            return await self._spawn(agent, args)

        tools: dict[str, ToolSpec] = {
            "write_artifact": ToolSpec(WRITE_SCHEMA, write_handler),
            "read_artifact": ToolSpec(READ_SCHEMA, read_handler),
            "finish": ToolSpec(FINISH_WORKER_SCHEMA, finish_handler),
        }
        if agent.depth < run.max_depth:
            tools["spawn_agent"] = ToolSpec(SPAWN_SCHEMA, spawn_handler)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": ROLE_PROMPTS[agent.role]},
            {"role": "user", "content": worker_user_message(agent.task, context)},
        ]
        try:
            result = await run_tool_loop(
                self.client,
                role=agent.role,
                messages=messages,
                tools=tools,
                max_steps=MAX_WORKER_STEPS,
                max_tokens=1800,
                terminal_tools=frozenset({"finish"}),
                on_step=lambda step: self._on_worker_step(agent, step),
                on_tool=lambda name, args, payload, invalid: self._on_tool(agent, name, args, payload, invalid),
            )
        except LlmError as error:
            agent.status = "config_error" if error.kind in ("structural_400", "auth") else "failed"
            agent.error_kind = error.kind
            agent.latency_ms += int((time.perf_counter() - started) * 1000)
            if error.kind == "structural_400" and "reasoning" in str(error).lower():
                run.flags.thinking_replay_broken = True
            self.store.append(
                run, "agent_failed", agent=agent,
                summary=f"{error.kind}: {_clip(str(error), 200)}",
                data={"kind": error.kind},
            )
            return {"agent_id": agent.id, "status": agent.status, "error": error.kind,
                    "summary": _clip(str(error), 300), "artifact_keys": list(agent.artifact_keys)}

        self._account(agent, result)
        agent.latency_ms += int((time.perf_counter() - started) * 1000)
        agent.summary = _clip(summary_box.get("summary") or result.content, MAX_SUMMARY_CHARS)
        agent.status = "done" if result.stop_reason == "finished_tool" else "partial"
        if agent.status == "partial":
            run.flags.unverified = True
        self.worker_summaries[agent.id] = agent.summary
        self.store.append(
            run, "agent_finished", agent=agent, summary=agent.summary,
            tokens_in=agent.tokens_in, tokens_out=agent.tokens_out, cost=agent.cost,
            latency_ms=agent.latency_ms,
            data={"status": agent.status, "stop_reason": result.stop_reason},
        )
        return {
            "agent_id": agent.id,
            "role": agent.role,
            "status": agent.status,
            "summary": agent.summary,
            "artifact_keys": list(agent.artifact_keys),
        }

    def _on_worker_step(self, agent: AgentNode, step: StepRecord) -> None:
        agent.steps += 1
        self.store.append(
            self.run,
            "agent_step",
            agent=agent,
            summary=_clip(step.content, 160) or ", ".join(tool["name"] for tool in step.tools),
            tokens_in=step.tokens_in,
            tokens_out=step.tokens_out,
            latency_ms=step.latency_ms,
        )


async def execute_run(run: RunState, client: LlmClient, store: RunStore) -> None:
    executor = RunExecutor(run, client, store)
    await executor.execute()