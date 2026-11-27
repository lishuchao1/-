"""Atomic run checkpoints on disk.

Saving serializes the full run state to ``<state_dir>/<run_id>.json`` through a
temp file plus ``os.replace``, so a crash mid-write cannot truncate the last
good checkpoint. Runs that were still active when the process died are marked
``interrupted`` on load and any stale reservations are cleared.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from .models import RunEvent, RunState

logger = logging.getLogger("agent_g.checkpoint")

MAX_FILES = 60


def checkpoint_path(state_dir: Path, run_id: str) -> Path:
    return state_dir / f"{run_id}.json"


def save_checkpoint(state_dir: Path, run: RunState) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = checkpoint_path(state_dir, run.run_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(run.to_checkpoint(), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_checkpoints(state_dir: Path) -> list[RunState]:
    if not state_dir.is_dir():
        return []
    loaded: list[RunState] = []
    files = sorted(state_dir.glob("*.json"), key=lambda path: path.stat().st_mtime)
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            run = RunState.from_checkpoint(raw)
        except Exception:
            logger.warning("skipping unreadable checkpoint %s", path.name, exc_info=True)
            continue
        if run.status in ("queued", "running"):
            _mark_interrupted(run)
        loaded.append(run)
    return loaded


def _mark_interrupted(run: RunState) -> None:
    run.status = "interrupted"
    run.ended_at = time.time()
    run.reserved_tokens = 0
    run.reservations.clear()
    run.debug["recovered_after_restart"] = True
    for agent in run.agent_list():
        if agent.status in ("queued", "running"):
            agent.status = "cancelled"
    run.events.append(
        RunEvent(
            id=run.next_event_id,
            ts=time.time(),
            kind="run_interrupted",
            summary="application restarted before the run finished",
            data={"recovered": True},
        )
    )
    run.next_event_id += 1


def prune(state_dir: Path, keep: int = MAX_FILES) -> None:
    if not state_dir.is_dir():
        return
    files = sorted(state_dir.glob("*.json"), key=lambda path: path.stat().st_mtime)
    for path in files[:-keep] if keep > 0 else files:
        try:
            path.unlink()
        except OSError:
            logger.warning("could not prune checkpoint %s", path.name)