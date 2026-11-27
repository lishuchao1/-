"""Offline orchestration tests against a scripted model.

Covers the fake-LLM layer of the test plan: soft budget signal (T1), hard
budget stop (T2), depth-scoped tools (T3), dedupe without extra calls (T5),
cancellation (T7/T16), agent cap (T8), context isolation (T9), token
reconciliation (T10), partial agents on reserve exhaustion (T12c),
artifact ownership (T13), the finish review gate (T14), unknown tools (T15)
and structural provider errors (T17).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from app.llm import LlmError
from app.orchestrator import execute_run
from app.prompts import SUPERVISOR_PROMPT, WRITER_PROMPT
from app.store import RunStore
from tests.fakes import (
    RecordingClient,
    last_payloads,
    make_run,
    result,
    tool,
    tool_result_count,
)

FINAL_ANSWER = "Supervisor final answer with enough characters to pass validation."


def basic_worker(messages: list[dict[str, Any]], role: str, *_: Any):
    if tool_result_count(messages) == 0:
        return result(
            tool_calls=[
                tool("write_artifact", {"key": f"{role}.draft", "content": f"{role} draft text"})
            ]
        )
    return result(tool_calls=[tool("finish", {"summary": f"{role} finished its draft"})])


def reviewer_worker(messages: list[dict[str, Any]], role: str, *_: Any):
    if tool_result_count(messages) == 0:
        return result(
            tool_calls=[
                tool(
                    "write_artifact",
                    {"key": "reviewer.verdict", "content": "PASS\nboth drafts are consistent"},
                )
            ]
        )
    return result(tool_calls=[tool("finish", {"summary": "verdict PASS"})])


def worker_for(role: str):
    return reviewer_worker if role == "reviewer" else basic_worker


def steps_script(
    steps: list[list[Any]],
    worker=None,
):
    """Supervisor emits `steps[n]` on its n-th call; workers use their own script."""

    def script(messages: list[dict[str, Any]], role: str, *_: Any):
        if role == "main":
            index = min(tool_result_count(messages), len(steps) - 1)
            return result(tool_calls=steps[index])
        return (worker or worker_for(role))(messages, role)

    return script


async def test_soft_limit_emits_once_and_run_finishes() -> None:
    store = RunStore()
    run = make_run(store, budget=10_000)

    def script(messages: list[dict[str, Any]], role: str, *_: Any):
        if role != "main":
            return basic_worker(messages, role)
        count = tool_result_count(messages)
        if count == 0:
            return result(
                tool_calls=[tool("spawn_agent", {"role": "writer", "task": "write the draft"})],
                tokens_in=9_200,
                tokens_out=0,
            )
        if count == 1:
            return result(tool_calls=[tool("skip_review", {"reason": "single draft task"})])
        return result(tool_calls=[tool("finish", {"final_answer": FINAL_ANSWER})])

    client = RecordingClient(script)
    await execute_run(run, client, store)
    kinds = [event.kind for event in run.events]
    assert run.status == "done", run.final_answer
    assert kinds.count("budget_soft_limit") == 1
    assert run.tokens_used >= run.budget_tokens * 0.9
    assert run.tokens_used <= run.budget_tokens


async def test_hard_budget_stop_keeps_filled_slots() -> None:
    store = RunStore()
    run = make_run(store, budget=10_000)
    client = RecordingClient(
        lambda messages, role, *_: (
            result(
                tool_calls=[tool("spawn_agent", {"role": "writer", "task": "draft fast"})],
                tokens_in=12_000,
                tokens_out=0,
            )
            if role == "main" and tool_result_count(messages) == 0
            else basic_worker(messages, role)
            if role != "main"
            else result(tool_calls=[tool("finish", {"final_answer": FINAL_ANSWER})])
        )
    )
    await execute_run(run, client, store)
    assert run.status == "budget_exhausted"
    assert run.budget_hard_stop is True
    assert "writer.draft" in run.slots
    kinds = [event.kind for event in run.events]
    assert kinds.count("budget_exhausted") == 1


async def test_worker_tools_follow_max_depth() -> None:
    for max_depth, expect_spawn in ((1, False), (2, True)):
        store = RunStore()
        run = make_run(store, max_depth=max_depth)
        client = RecordingClient(
            steps_script(
                [
                    [tool("spawn_agent", {"role": "writer", "task": "write something"})],
                    [tool("skip_review", {"reason": "no review needed"})],
                    [tool("finish", {"final_answer": FINAL_ANSWER})],
                ]
            )
        )
        await execute_run(run, client, store)
        worker_calls = [call for call in client.calls if call["role"] == "writer"]
        assert worker_calls, "writer never ran"
        assert ("spawn_agent" in worker_calls[0]["tools"]) is expect_spawn


async def test_duplicate_spawn_reuses_previous_agent() -> None:
    store = RunStore()
    run = make_run(store)
    same = {"role": "writer", "task": "write the exact same draft"}
    client = RecordingClient(
        steps_script(
            [
                [tool("spawn_agent", same)],
                [tool("spawn_agent", same)],
                [tool("skip_review", {"reason": "dedupe test"})],
                [tool("finish", {"final_answer": FINAL_ANSWER})],
            ]
        )
    )
    await execute_run(run, client, store)
    worker_calls = [call for call in client.calls if call["role"] == "writer"]
    assert len(worker_calls) == 2, "dedupe must not call the model again"
    payloads = last_payloads(client.calls[-1]["messages"])
    assert any(payload.get("error") == "duplicate_task" for payload in payloads)
    kinds = [event.kind for event in run.events]
    assert "dedupe_skipped" in kinds
    assert run.status == "done"


class SlowClient:
    """Blocks on the first model call so the test can cancel mid-run."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, *_: Any, **__: Any):
        self.calls += 1
        await asyncio.sleep(30)
        raise AssertionError("cancelled client should never return")

    async def aclose(self) -> None:
        return None


async def test_cancel_propagates_and_flags_underreporting() -> None:
    store = RunStore()
    run = make_run(store)
    client = SlowClient()
    task = asyncio.create_task(execute_run(run, client, store))
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert run.status == "cancelled"
    assert all(agent.status == "cancelled" for agent in run.agent_list())
    assert run.flags.tokens_may_be_underreported is True
    assert run.tokens_used <= sum(
        agent.tokens_in + agent.tokens_out for agent in run.agent_list()
    )
    event_count = len(run.events)
    await asyncio.sleep(0.05)
    assert len(run.events) == event_count
    assert run.events[-1].kind == "run_finished"


async def test_agent_cap_is_enforced() -> None:
    store = RunStore()
    run = make_run(store)
    spawns = [
        tool("spawn_agent", {"role": "writer", "task": f"draft part {index}"})
        for index in range(13)
    ]
    client = RecordingClient(
        steps_script(
            [
                spawns,
                [tool("skip_review", {"reason": "cap test"})],
                [tool("finish", {"final_answer": FINAL_ANSWER})],
            ]
        )
    )
    await execute_run(run, client, store)
    workers = [agent for agent in run.agent_list() if agent.depth > 0]
    assert len(workers) == 12
    assert run.status == "done"
    cap_events = [
        event
        for event in run.events
        if event.kind == "limit_reached" and event.data.get("limit") == "agents"
    ]
    assert cap_events


async def test_worker_context_is_isolated() -> None:
    store = RunStore()
    run = make_run(store)
    client = RecordingClient(
        steps_script(
            [
                [
                    tool(
                        "spawn_agent",
                        {"role": "writer", "task": "draft alpha", "context": "CTX_ALPHA"},
                    ),
                    tool(
                        "spawn_agent",
                        {"role": "writer", "task": "draft beta", "context": "CTX_BETA"},
                    ),
                ],
                [tool("skip_review", {"reason": "isolation test"})],
                [tool("finish", {"final_answer": FINAL_ANSWER})],
            ]
        )
    )
    await execute_run(run, client, store)
    supervisor_calls = [call for call in client.calls if call["role"] == "main"]
    assert SUPERVISOR_PROMPT in supervisor_calls[0]["messages"][0]["content"]
    worker_calls = [call for call in client.calls if call["role"] == "writer"]
    assert len(worker_calls) == 4
    alpha = [call for call in worker_calls if "CTX_ALPHA" in str(call["messages"])]
    beta = [call for call in worker_calls if "CTX_BETA" in str(call["messages"])]
    assert len(alpha) == 2 and len(beta) == 2
    for call in alpha:
        joined = str(call["messages"])
        assert "CTX_BETA" not in joined
        assert SUPERVISOR_PROMPT not in joined
        assert call["messages"][0]["content"] == WRITER_PROMPT
    for call in beta:
        assert "CTX_ALPHA" not in str(call["messages"])


async def test_tokens_reconcile_and_review_passes() -> None:
    store = RunStore()
    run = make_run(store)
    client = RecordingClient(
        steps_script(
            [
                [
                    tool("spawn_agent", {"role": "writer", "task": "draft one"}),
                    tool("spawn_agent", {"role": "marketing", "task": "plan one"}),
                    tool("spawn_agent", {"role": "reviewer", "task": "review both"}),
                ],
                [tool("finish", {"final_answer": FINAL_ANSWER})],
            ]
        )
    )
    await execute_run(run, client, store)
    assert run.status == "done"
    assert run.flags.unverified is False
    assert run.debug.get("review_verdict") == "PASS"
    summed = sum(agent.tokens_in + agent.tokens_out for agent in run.agent_list())
    assert run.tokens_used == summed
    kinds = [event.kind for event in run.events]
    assert "review_passed" in kinds
    assert run.slots["reviewer.verdict"]["status"] == "filled"


async def test_reserve_exhaustion_leaves_partial_worker() -> None:
    store = RunStore()
    run = make_run(store, budget=10_000)
    client = RecordingClient(
        lambda messages, role, *_: (
            result(
                tool_calls=[tool("spawn_agent", {"role": "writer", "task": "expensive draft"})],
                tokens_in=10,
                tokens_out=0,
            )
            if role == "main" and tool_result_count(messages) == 0
            else result(
                tool_calls=[
                    tool("write_artifact", {"key": "writer.big", "content": "big draft body"})
                ],
                tokens_in=12_000,
                tokens_out=0,
            )
            if role == "writer" and tool_result_count(messages) == 0
            else result(tool_calls=[tool("finish", {"summary": "should not be reached"})])
            if role == "writer"
            else result(tool_calls=[tool("finish", {"final_answer": FINAL_ANSWER})])
        )
    )
    await execute_run(run, client, store)
    writer = next(agent for agent in run.agent_list() if agent.role == "writer")
    assert writer.status == "partial"
    assert writer.error_kind == ""
    assert run.status == "budget_exhausted"
    assert run.tokens_used == 12_010
    assert run.reserved_tokens == 0
    assert run.reservations == {}


async def test_wrong_prefix_is_rejected_without_writing() -> None:
    store = RunStore()
    run = make_run(store)

    def script(messages: list[dict[str, Any]], role: str, *_: Any):
        if role == "main":
            count = tool_result_count(messages)
            if count == 0:
                return result(
                    tool_calls=[tool("spawn_agent", {"role": "writer", "task": "draft"})]
                )
            if count == 1:
                return result(tool_calls=[tool("finish", {"final_answer": FINAL_ANSWER})])
            return result(tool_calls=[tool("finish", {"final_answer": FINAL_ANSWER})])
        count = tool_result_count(messages)
        if count == 0:
            return result(
                tool_calls=[
                    tool("write_artifact", {"key": "marketing.plan", "content": "stolen slot"})
                ]
            )
        if count == 1:
            return result(
                tool_calls=[
                    tool("write_artifact", {"key": "writer.draft", "content": "own draft"})
                ]
            )
        return result(tool_calls=[tool("finish", {"summary": "owned draft written"})])

    client = RecordingClient(script)
    await execute_run(run, client, store)
    assert not any(key.startswith("marketing.") for key in run.slots)
    writer_calls = [call for call in client.calls if call["role"] == "writer"]
    payloads = last_payloads(writer_calls[-1]["messages"])
    assert any(payload.get("error") == "wrong_prefix" for payload in payloads)
    assert run.status == "done"


async def test_finish_without_review_is_blocked_once() -> None:
    store = RunStore()
    run = make_run(store)
    client = RecordingClient(
        steps_script(
            [
                [tool("spawn_agent", {"role": "writer", "task": "draft"})],
                [tool("finish", {"final_answer": FINAL_ANSWER})],
                [tool("finish", {"final_answer": FINAL_ANSWER})],
            ]
        )
    )
    await execute_run(run, client, store)
    kinds = [event.kind for event in run.events]
    assert "finish_blocked" in kinds
    assert run.status == "done"
    assert run.flags.unverified is True
    payloads = last_payloads(client.calls[-1]["messages"])
    assert any(payload.get("error") == "review_not_completed" for payload in payloads)


async def test_skip_review_passes_with_unverified_flag() -> None:
    store = RunStore()
    run = make_run(store)
    client = RecordingClient(
        steps_script(
            [
                [tool("spawn_agent", {"role": "writer", "task": "draft"})],
                [tool("skip_review", {"reason": "the task has nothing to review"})],
                [tool("finish", {"final_answer": FINAL_ANSWER})],
            ]
        )
    )
    await execute_run(run, client, store)
    assert run.status == "done"
    assert run.flags.unverified is True
    assert "review_skipped" in [event.kind for event in run.events]
    assert run.debug.get("review_skipped")


async def test_unknown_tool_is_recorded_not_fatal() -> None:
    store = RunStore()
    run = make_run(store)
    client = RecordingClient(
        steps_script(
            [
                [tool("summon_dragon", {"power": 9})],
                [tool("skip_review", {"reason": "unknown tool test"})],
                [tool("finish", {"final_answer": FINAL_ANSWER})],
            ]
        )
    )
    await execute_run(run, client, store)
    invalid = [event for event in run.events if event.kind == "invalid_tool_call"]
    assert invalid and invalid[0].data.get("reason") == "unknown_tool"
    assert run.status == "done"


async def test_structural_error_marks_config_error() -> None:
    store = RunStore()
    run = make_run(store)

    class FailingClient:
        calls = 0

        async def complete(self, *_: Any, **__: Any):
            FailingClient.calls += 1
            raise LlmError("structural_400", "400: reasoning_content is not allowed", status=400)

        async def aclose(self) -> None:
            return None

    await execute_run(run, FailingClient(), store)
    assert run.status == "failed"
    root = run.agent_list()[0]
    assert root.status == "config_error"
    assert root.error_kind == "structural_400"
    assert run.flags.thinking_replay_broken is True
    assert FailingClient.calls == 1
    assert run.final_answer.startswith("run failed: structural_400")