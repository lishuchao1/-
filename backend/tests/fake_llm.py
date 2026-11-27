"""Deterministic stand-ins for the provider, used by tests and offline demos.

The fake exposes the same async surface as LlmClient and drives the
orchestrator through scripted tool calls without any network access.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from uuid import uuid4

from app.llm import LlmResult, ToolCall, Usage


def _tool_call(name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(id=f"call_{uuid4().hex[:8]}", name=name, arguments=json.dumps(arguments))


def _has_tool_result(messages: list[dict[str, Any]]) -> bool:
    return any(message.get("role") == "tool" for message in messages)


def _tool_result_count(messages: list[dict[str, Any]]) -> int:
    return sum(1 for message in messages if message.get("role") == "tool")


class ScriptedClient:
    """Supervisor plans two parallel spawns, writers write then finish.

    Each request sleeps `delay_s` to make concurrency observable.
    """

    def __init__(self, delay_s: float = 0.2, calls_per_role: int | None = None):
        self.delay_s = delay_s
        self.timestamps: list[tuple[float, float, str]] = []
        self.call_names: list[str] = []
        self.max_concurrent = 0
        self._active = 0

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        role: str = "main",
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ) -> LlmResult:
        self._active += 1
        self.max_concurrent = max(self.max_concurrent, self._active)
        started = time.perf_counter()
        try:
            await asyncio.sleep(self.delay_s)
            result = self._script(messages, role)
        finally:
            self._active -= 1
        self.call_names.append(role)
        self.timestamps.append((started, time.perf_counter(), role))
        return result

    def _script(self, messages: list[dict[str, Any]], role: str) -> LlmResult:
        usage = Usage(tokens_in=10, tokens_out=5, cost=0.0)
        if role == "main":
            if _tool_result_count(messages) == 0:
                return LlmResult(
                    content="",
                    tool_calls=[
                        _tool_call(
                            "spawn_agent",
                            {"role": "writer", "task": "write part A", "context": "KEY=writer.a"},
                        ),
                        _tool_call(
                            "spawn_agent",
                            {"role": "writer", "task": "write part B", "context": "KEY=writer.b"},
                        ),
                    ],
                    usage=usage,
                    finish_reason="tool_calls",
                )
            return LlmResult(
                content="",
                tool_calls=[_tool_call("finish", {"final_answer": "combined answer"})],
                usage=usage,
                finish_reason="tool_calls",
            )

        key = "writer.a" if "part A" in json.dumps(messages, ensure_ascii=False) else "writer.b"
        if not _has_tool_result(messages):
            return LlmResult(
                content="",
                tool_calls=[
                    _tool_call("write_artifact", {"key": key, "content": f"content for {key}"})
                ],
                usage=usage,
                finish_reason="tool_calls",
            )
        return LlmResult(
            content="",
            tool_calls=[_tool_call("finish", {"summary": f"wrote {key}"})],
            usage=usage,
            finish_reason="tool_calls",
        )

    async def aclose(self) -> None:
        return None


class BrokenClient:
    """Always raises the provided error, for failure-path tests."""

    def __init__(self, error: Exception):
        self.error = error
        self.calls = 0

    async def complete(self, *_: Any, **__: Any) -> LlmResult:
        self.calls += 1
        raise self.error

    async def aclose(self) -> None:
        return None