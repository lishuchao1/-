"""Artifact ownership: role prefixes, slot metadata and overwrite events.

Contents live only in RunState.artifact_contents; the public slot list carries
metadata so the API never leaks draft text by accident.
"""

from __future__ import annotations

import re
from typing import Any

from .models import AgentNode, RunState
from .prompts import ROLE_PREFIX
from .store import RunStore

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_.-]*$")
MAX_KEY_LEN = 80
MAX_CONTENT_CHARS = 20_000


class ArtifactError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _validate_key(agent: AgentNode, key: str) -> str:
    cleaned = key.strip()
    if not cleaned or len(cleaned) > MAX_KEY_LEN or not KEY_PATTERN.match(cleaned):
        raise ArtifactError("invalid_key", "key must look like role.slot, lowercase, max 80 chars")
    prefix = ROLE_PREFIX.get(agent.role)
    if prefix is None:
        raise ArtifactError("invalid_role", f"role {agent.role} cannot write artifacts")
    if not cleaned.startswith(prefix):
        raise ArtifactError("wrong_prefix", f"{agent.role} may only write keys starting with {prefix}")
    return cleaned


def write_artifact(
    store: RunStore,
    run: RunState,
    agent: AgentNode,
    key: str,
    content: str,
) -> dict[str, Any]:
    cleaned = _validate_key(agent, key)
    if not content.strip():
        raise ArtifactError("empty_content", "content must not be empty")
    if len(content) > MAX_CONTENT_CHARS:
        raise ArtifactError("content_too_large", f"content exceeds {MAX_CONTENT_CHARS} chars")

    previous = run.slots.get(cleaned)
    version = int(previous["version"]) + 1 if previous else 1
    run.artifact_contents[cleaned] = content
    run.slots[cleaned] = {
        "key": cleaned,
        "owner": agent.role,
        "last_agent": agent.id,
        "status": "filled",
        "version": version,
        "chars": len(content),
    }

    if cleaned not in agent.artifact_keys:
        agent.artifact_keys.append(cleaned)
    if previous is None:
        store.append(
            run,
            "artifact_written",
            agent=agent,
            summary=f"{cleaned} ({len(content)} chars)",
            data={"key": cleaned, "version": version},
        )
    else:
        store.append(
            run,
            "artifact_overwrite",
            agent=agent,
            summary=f"{cleaned} v{version}",
            data={"key": cleaned, "version": version, "previous_agent": previous.get("owner", "")},
        )
    return {"ok": True, "key": cleaned, "version": version, "chars": len(content)}


def read_artifact(run: RunState, key: str, limit: int = 2500) -> str:
    cleaned = key.strip()
    content = run.artifact_contents.get(cleaned)
    if content is None:
        raise ArtifactError("missing", f"artifact {cleaned} does not exist")
    if len(content) > limit:
        return content[:limit] + f"\n...[truncated {len(content) - limit} chars]"
    return content


def required_slots(run: RunState) -> dict[str, bool]:
    """Slots the finish step requires before a run can count as verified."""
    checks = {
        "writer": any(key.startswith("writer.") for key in run.slots),
        "marketing": any(key.startswith("marketing.") for key in run.slots),
        "reviewer": "reviewer.verdict" in run.slots,
    }
    return checks


def verdict_of(run: RunState) -> str:
    content = run.artifact_contents.get("reviewer.verdict", "")
    if not content.strip():
        return ""
    first_line = content.strip().splitlines()[0].strip()
    token = first_line.split(":", 1)[0].strip().upper()
    return token if token in ("PASS", "REJECT") else ""