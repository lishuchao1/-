"""Checkpoint persistence and resume without re-running finished agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.artifacts import write_artifact
from app.checkpoint import load_checkpoints, save_checkpoint
from app.orchestrator import ResumeError, execute_run, prepare_resume, resume_brief
from app.store import RunStore
from tests.fakes import (
    RecordingClient,
    last_payloads,
    make_run,
    result,
    tool,
    tool_result_count,
)

FINAL_ANSWER = "Resumed supervisor answer with enough characters to be accepted."


def seed_interrupted_run(store: RunStore):
    run = make_run(store, budget=30_000)
    writer = store.add_agent(run, role="writer", task="draft the first section", parent_id=None, depth=1)
    write_artifact(store, run, writer, "writer.draft", "previous draft body")
    writer.status = "done"
    writer.summary = "previous draft summary"
    run.tokens_used = 5_000
    run.status = "budget_exhausted"
    run.reserved_tokens = 900
    run.reservations = {"a9": 900}
    run.flags.unverified = True
    return run, writer


def test_checkpoint_roundtrip_marks_active_run_interrupted(tmp_path: Path) -> None:
    store = RunStore()
    run = make_run(store)
    agent = store.add_agent(run, role="writer", task="draft", parent_id=None, depth=1)
    agent.status = "running"
    agent.tokens_in = 10
    run.tokens_used = 10
    run.reservations[agent.id] = 500
    run.reserved_tokens = 500
    store.append(run, "agent_started", agent=agent, summary="writer")

    save_checkpoint(tmp_path, run)
    loaded = load_checkpoints(tmp_path)
    assert len(loaded) == 1
    restored = loaded[0]
    assert restored.run_id == run.run_id
    assert restored.status == "interrupted"
    assert restored.reservations == {}
    assert restored.reserved_tokens == 0
    assert restored.agents[agent.id].status == "cancelled"
    assert restored.events[-1].kind == "run_interrupted"
    assert restored.artifact_contents == run.artifact_contents


def test_prepare_resume_rejects_active_and_spent_runs() -> None:
    store = RunStore()
    run = make_run(store)
    run.status = "running"
    with pytest.raises(ResumeError) as active:
        prepare_resume(run, 10_000)
    assert active.value.code == "run_active"

    run.status = "done"
    with pytest.raises(ResumeError) as done:
        prepare_resume(run, 10_000)
    assert done.value.code == "not_resumable"

    run.status = "budget_exhausted"
    run.tokens_used = run.budget_tokens - 10
    with pytest.raises(ResumeError) as small:
        prepare_resume(run, None)
    assert small.value.code == "budget_too_small"


def test_prepare_resume_resets_transient_state() -> None:
    store = RunStore()
    run, _ = seed_interrupted_run(store)
    prepare_resume(run, 20_000)
    assert run.status == "queued"
    assert run.budget_tokens == 50_000
    assert run.reserved_tokens == 0
    assert run.reservations == {}
    assert run.budget_hard_stop is False
    assert run.flags.unverified is False
    assert run.debug["resume_from"] == "budget_exhausted"

    brief = resume_brief(run)
    assert "RESUMED RUN" in brief
    assert "writer.draft" in brief
    assert "reviewer" in brief


async def test_resume_reuses_finished_agent_and_skips_its_model_calls() -> None:
    store = RunStore()
    run, writer = seed_interrupted_run(store)
    prepare_resume(run, 20_000)

    def script(messages: list[dict[str, Any]], role: str, *_: Any):
        if role == "main":
            count = tool_result_count(messages)
            if count == 0:
                return result(
                    tool_calls=[
                        tool("spawn_agent", {"role": "writer", "task": "draft the first section"})
                    ]
                )
            if count == 1:
                return result(
                    tool_calls=[tool("spawn_agent", {"role": "reviewer", "task": "review drafts"})]
                )
            return result(tool_calls=[tool("finish", {"final_answer": FINAL_ANSWER})])
        if role == "reviewer":
            if tool_result_count(messages) == 0:
                return result(
                    tool_calls=[
                        tool(
                            "write_artifact",
                            {"key": "reviewer.verdict", "content": "PASS\nresumed review"},
                        )
                    ]
                )
            return result(tool_calls=[tool("finish", {"summary": "resumed review passed"})])
        raise AssertionError(f"unexpected worker role {role}")

    client = RecordingClient(script)
    await execute_run(run, client, store, resume=True)

    writer_calls = [call for call in client.calls if call["role"] == "writer"]
    assert writer_calls == [], "a finished agent must not be re-run on resume"
    assert run.status == "done"
    assert run.final_answer == FINAL_ANSWER
    payloads = last_payloads(client.calls[-1]["messages"])
    assert any(payload.get("error") == "duplicate_task" for payload in payloads)
    kinds = [event.kind for event in run.events]
    assert "run_resumed" in kinds
    assert run.debug.get("review_verdict") == "PASS"

    supervisor_messages = client.calls[0]["messages"]
    assert any("RESUMED RUN" in str(message.get("content", "")) for message in supervisor_messages)
    assert any("writer.draft" in str(message.get("content", "")) for message in supervisor_messages)