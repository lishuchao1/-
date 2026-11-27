"""Artifact ownership rules: prefixes, overwrite events, metadata leakage."""

from __future__ import annotations

from app.artifacts import ArtifactError, read_artifact, required_slots, verdict_of, write_artifact
from app.models import AgentNode, RunState
from app.store import RunStore


def make_run(budget: int = 100_000) -> tuple[RunStore, RunState, AgentNode]:
    store = RunStore()
    run = store.create("artifact test", budget_tokens=budget, max_depth=2, max_concurrency=2)
    agent = store.add_agent(run, role="writer", task="draft", parent_id=None, depth=1)
    return store, run, agent


def test_writer_cannot_write_other_prefix() -> None:
    store, run, agent = make_run()
    try:
        write_artifact(store, run, agent, "marketing.plan", "hello")
    except ArtifactError as error:
        assert error.code == "wrong_prefix"
    else:
        raise AssertionError("wrong prefix should be rejected")


def test_invalid_key_rejected() -> None:
    store, run, agent = make_run()
    for key in ("Draft", "writer", "writer.", "writer..x", "writer.x y"):
        try:
            write_artifact(store, run, agent, key, "text")
        except ArtifactError as error:
            assert error.code == "invalid_key", key
        else:
            raise AssertionError(f"key {key!r} should be rejected")


def test_overwrite_increments_version_and_emits_event() -> None:
    store, run, agent = make_run()
    write_artifact(store, run, agent, "writer.draft", "v1")
    write_artifact(store, run, agent, "writer.draft", "v2 longer")
    slot = run.slots["writer.draft"]
    assert slot["version"] == 2
    assert slot["last_agent"] == agent.id
    kinds = [event.kind for event in run.events]
    assert kinds.count("artifact_written") == 1
    assert kinds.count("artifact_overwrite") == 1


def test_public_slots_do_not_leak_content() -> None:
    store, run, agent = make_run()
    write_artifact(store, run, agent, "writer.draft", "secret draft text")
    public = run.public()
    assert public["slots"][0]["chars"] == len("secret draft text")
    assert "secret draft text" not in repr(public)
    assert run.artifact_contents["writer.draft"] == "secret draft text"


def test_read_missing_and_truncation() -> None:
    store, run, agent = make_run()
    try:
        read_artifact(run, "writer.missing")
    except ArtifactError as error:
        assert error.code == "missing"
    else:
        raise AssertionError("missing artifact should raise")
    write_artifact(store, run, agent, "writer.long", "x" * 3000)
    text = read_artifact(run, "writer.long", limit=100)
    assert text.startswith("x" * 100) and "truncated" in text


def test_required_slots_and_verdict() -> None:
    store, run, agent = make_run()
    assert required_slots(run) == {"writer": False, "marketing": False, "reviewer": False}
    write_artifact(store, run, agent, "writer.draft", "draft")
    reviewer = store.add_agent(run, role="reviewer", task="review", parent_id=None, depth=1)
    write_artifact(store, run, reviewer, "reviewer.verdict", "REJECT: needs work")
    checks = required_slots(run)
    assert checks["writer"] and checks["reviewer"] and not checks["marketing"]
    assert verdict_of(run) == "REJECT"