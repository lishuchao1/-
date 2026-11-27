"""Supervisor-driven orchestration.

The supervisor plans at runtime through tool calls; there is no hardcoded
pipeline. Sub-agents run with isolated context and return only a summary plus
artifact keys, so the parent sees evidence rather than raw transcripts.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from .artifacts import ArtifactError, read_artifact, required_slots, verdict_of, write_artifact
from .budget import BudgetLedger
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
        self.ledger = BudgetLedger(run, settings.budget_reserve_tokens)
        self.final_answer = ""
        self.worker_summaries: dict[str, str] = {}
        self._budget_exhausted_reported = False

    async def execute(self) -> None:
        run = self.run
        run.status = "running"
        run.started_at = time.time()
        self.store.append(run, "run_started", summary=_clip(run.task, 120))
        root = self.store.add_agent(run, role="supervisor", task=run.task, parent_id=None, depth=0)
        executor_task = asyncio.current_task()
        watchdog = asyncio.create_task(self._watch_stall(executor_task))
        try:
            await self._supervise(root)
            if run.budget_hard_stop:
                run.status = "budget_exhausted"
                run.flags.unverified = True
            elif run.final_answer:
                run.status = "done"
            else:
                run.status = "failed"
        except LlmError as error:
            run.status = "failed"
            run.final_answer = f"run failed: {error.kind}: {_clip(str(error), 300)}"
            root.status = "config_error" if error.kind in ("structural_400", "auth") else "failed"
            if error.kind == "structural_400" and "reasoning" in str(error).lower():
                run.flags.thinking_replay_broken = True
            if error.kind == "breaker_open":
                self.store.append(
                    run, "breaker_open", agent=root,
                    summary="provider circuit breaker is open",
                )
            self.store.append(
                run,
                "agent_failed",
                agent=root,
                summary=f"{error.kind}: {_clip(str(error), 200)}",
                data={"kind": error.kind, "status": error.status},
            )
        except asyncio.CancelledError:
            if run.debug.get("watchdog_fired"):
                run.status = "interrupted"
                root.status = "cancelled"
            else:
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
            watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog
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

    async def _watch_stall(self, executor_task: asyncio.Task[None] | None) -> None:
        run = self.run
        timeout = settings.stall_timeout_s
        interval = max(0.5, min(5.0, timeout / 4))
        warned = False
        while True:
            await asyncio.sleep(interval)
            last_seen = run.events[-1].ts if run.events else (run.started_at or run.created_at)
            idle = time.time() - last_seen
            if not warned and idle >= timeout * 0.6:
                warned = True
                self.store.append(
                    run, "stall_warning",
                    summary=f"no events for {int(idle)}s",
                    data={"idle_s": round(idle, 1), "timeout_s": timeout},
                )
            if idle >= timeout:
                run.debug["watchdog_fired"] = True
                self.store.append(
                    run, "run_interrupted",
                    summary=f"no progress for {int(idle)}s; watchdog stopped the run",
                    data={"idle_s": round(idle, 1)},
                )
                if executor_task is not None and not executor_task.done():
                    executor_task.cancel()
                return

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
            parallel_tools=frozenset({"spawn_agent"}),
            budget_guard=self._budget_guard,
            on_step=lambda step: self._on_supervisor_step(root, step),
            on_tool=lambda name, args, payload, invalid: self._on_tool(root, name, args, payload, invalid),
        )
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
        self._charge_step(root, step)
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

    def _charge_step(self, agent: AgentNode, step: StepRecord) -> None:
        run = self.run
        price_in, price_out = settings.price_for(agent.role)
        cost = step.tokens_in / 1e6 * price_in + step.tokens_out / 1e6 * price_out
        agent.tokens_in += step.tokens_in
        agent.tokens_out += step.tokens_out
        agent.cost = round(agent.cost + cost, 8)
        run.cost = round(run.cost + cost, 8)
        self.ledger.charge(agent.id, step.tokens_in + step.tokens_out)
        if step.used_fallback:
            self.store.append(
                run, "provider_fallback", agent=agent,
                summary="primary provider failed; fallback answered",
            )
        if self.ledger.soft_limit_reached() and not run.budget_soft_reported:
            run.budget_soft_reported = True
            self.store.append(
                run,
                "budget_soft_limit",
                agent=agent,
                summary=f"consumed {run.tokens_used}/{run.budget_tokens} tokens",
                data={"budget_tokens": run.budget_tokens, "tokens_used": run.tokens_used},
            )
        if self.ledger.exhausted:
            self._emit_budget_exhausted(agent)

    def _budget_guard(self) -> bool:
        if self.ledger.exhausted:
            self._emit_budget_exhausted()
            return False
        return True

    def _emit_budget_exhausted(self, agent: AgentNode | None = None) -> None:
        if self._budget_exhausted_reported:
            return
        self._budget_exhausted_reported = True
        self.run.budget_hard_stop = True
        self.store.append(
            self.run,
            "budget_exhausted",
            agent=agent,
            summary=f"budget {self.run.budget_tokens} tokens exhausted",
            data={"tokens_used": self.run.tokens_used, "reserved": self.run.reserved_tokens},
        )

    async def _spawn(self, parent: AgentNode, args: dict[str, Any]) -> dict[str, Any]:
        run = self.run
        role = str(args.get("role", "")).strip()
        task = str(args.get("task", "")).strip()
        context = str(args.get("context", "") or "")[: settings.context_max_chars]

        if role not in ROLE_PROMPTS:
            return {"error": "invalid_role", "detail": f"role must be one of {sorted(ROLE_PROMPTS)}"}
        if not task:
            return {"error": "invalid_task", "detail": "task must not be empty"}
        normalized = " ".join(task.lower().split())
        for existing in run.agents.values():
            if (
                existing.role == role
                and " ".join(existing.task.lower().split()) == normalized
                and existing.status in ("queued", "running", "done", "partial")
            ):
                self.store.append(
                    run,
                    "dedupe_skipped",
                    agent=parent,
                    summary=f"{role} already handled this task as {existing.id}",
                    data={"duplicate_of": existing.id, "role": role},
                )
                return {
                    "error": "duplicate_task",
                    "detail": f"{existing.id} already handled an identical task; reuse its artifacts",
                    "agent_id": existing.id,
                    "status": existing.status,
                    "summary": existing.summary,
                    "artifact_keys": list(existing.artifact_keys),
                }
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
        reserved = self.ledger.reserve(child.id)
        if reserved is None:
            child.status = "failed"
            if self.ledger.exhausted:
                child.error_kind = "budget_exhausted"
                self._emit_budget_exhausted(child)
                return {
                    "error": "budget_exhausted",
                    "detail": "token budget is exhausted; finish with what you have",
                    "budget_remaining": 0,
                }
            child.error_kind = "budget_unavailable"
            self.store.append(
                run, "limit_reached", agent=child,
                summary="budget fully reserved by running agents",
                data={"limit": "budget_reserved", "reserved": run.reserved_tokens},
            )
            return {
                "error": "budget_unavailable",
                "detail": "remaining budget is currently reserved by running agents; retry later or finish",
                "budget_remaining": self.ledger.remaining,
            }
        self.store.append(
            run, "agent_spawned", agent=child, summary=_clip(task, 160),
            data={"role": role, "parent": parent.id, "reserved_tokens": reserved},
        )
        self.store.append(
            run, "budget_reserved", agent=child,
            summary=f"reserved {reserved} tokens",
            data={"reserved": reserved, "remaining": self.ledger.remaining},
        )
        result = await self._run_worker(child, context)
        result["budget_remaining"] = self.ledger.remaining
        return result

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
                parallel_tools=frozenset({"spawn_agent"}),
                budget_guard=self._budget_guard,
                on_step=lambda step: self._on_worker_step(agent, step),
                on_tool=lambda name, args, payload, invalid: self._on_tool(agent, name, args, payload, invalid),
            )
        except LlmError as error:
            agent.status = "config_error" if error.kind in ("structural_400", "auth") else "failed"
            agent.error_kind = error.kind
            agent.latency_ms += int((time.perf_counter() - started) * 1000)
            if error.kind == "structural_400" and "reasoning" in str(error).lower():
                run.flags.thinking_replay_broken = True
            if error.kind == "breaker_open":
                self.store.append(
                    run, "breaker_open", agent=agent,
                    summary="provider circuit breaker is open",
                )
            self.store.append(
                run, "agent_failed", agent=agent,
                summary=f"{error.kind}: {_clip(str(error), 200)}",
                data={"kind": error.kind},
            )
            self._settle_agent(agent)
            return {"agent_id": agent.id, "status": agent.status, "error": error.kind,
                    "summary": _clip(str(error), 300), "artifact_keys": list(agent.artifact_keys)}
        except asyncio.CancelledError:
            agent.status = "cancelled"
            self._settle_agent(agent)
            raise

        agent.latency_ms += int((time.perf_counter() - started) * 1000)
        agent.summary = _clip(summary_box.get("summary") or result.content, MAX_SUMMARY_CHARS)
        agent.status = "done" if result.stop_reason == "finished_tool" else "partial"
        if agent.status == "partial":
            run.flags.unverified = True
        self.worker_summaries[agent.id] = agent.summary
        refunded = self._settle_agent(agent)
        self.store.append(
            run, "agent_finished", agent=agent, summary=agent.summary,
            tokens_in=agent.tokens_in, tokens_out=agent.tokens_out, cost=agent.cost,
            latency_ms=agent.latency_ms,
            data={"status": agent.status, "stop_reason": result.stop_reason, "refunded": refunded},
        )
        return {
            "agent_id": agent.id,
            "role": agent.role,
            "status": agent.status,
            "summary": agent.summary,
            "artifact_keys": list(agent.artifact_keys),
        }

    def _settle_agent(self, agent: AgentNode) -> int:
        refunded = self.ledger.release(agent.id)
        self.store.append(
            self.run,
            "budget_settled",
            agent=agent,
            summary=f"used {agent.tokens_in + agent.tokens_out} tokens, refunded {refunded}",
            data={
                "actual_tokens": agent.tokens_in + agent.tokens_out,
                "refunded": refunded,
                "remaining": self.ledger.remaining,
            },
        )
        return refunded

    def _on_worker_step(self, agent: AgentNode, step: StepRecord) -> None:
        agent.steps += 1
        self._charge_step(agent, step)
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