"""Fake model clients and builders shared by the offline test suite."""

from __future__ import annotations

import copy
import json
from typing import Any, Callable
from uuid import uuid4

from app.llm import LlmClient, LlmResult, ToolCall, Usage
from app.models import RunState
from app.store import RunStore

Script = Callable[[list[dict[str, Any]], str, list[dict[str, Any]] | None, int], LlmResult]


def tool(name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(
        id=f"call_{uuid4().hex[:8]}",
        name=name,
        arguments=json.dumps(arguments, ensure_ascii=False),
    )


def result(
    *,
    tool_calls: list[ToolCall] | None = None,
    content: str = "",
    tokens_in: int = 10,
    tokens_out: int = 5,
    reasoning_content: str = "",
    finish_reason: str = "tool_calls",
) -> LlmResult:
    return LlmResult(
        content=content,
        tool_calls=tool_calls or [],
        reasoning_content=reasoning_content,
        usage=Usage(tokens_in=tokens_in, tokens_out=tokens_out, cost=0.0),
        latency_ms=1,
        model="fake-model",
        finish_reason=finish_reason if tool_calls else "stop",
    )


def tool_result_count(messages: list[dict[str, Any]]) -> int:
    return sum(1 for message in messages if message.get("role") == "tool")


def last_payload(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in reversed(messages):
        if message.get("role") == "tool":
            try:
                return json.loads(message.get("content") or "{}")
            except json.JSONDecodeError:
                return {}
    return {}


def last_payloads(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        try:
            payloads.append(json.loads(message.get("content") or "{}"))
        except json.JSONDecodeError:
            payloads.append({})
    return payloads


class RecordingClient:
    """Records every request (role, message snapshot, tool names) and replies via a script."""

    def __init__(self, script: Script):
        self.script = script
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        role: str = "main",
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ) -> LlmResult:
        index = len(self.calls)
        self.calls.append(
            {
                "role": role,
                "messages": copy.deepcopy(messages),
                "tools": [spec["function"]["name"] for spec in tools or []],
            }
        )
        return self.script(messages, role, tools, index)

    async def aclose(self) -> None:
        return None


def make_run(
    store: RunStore,
    *,
    budget: int = 100_000,
    max_depth: int = 2,
    max_concurrency: int = 3,
    task: str = "offline orchestration test",
) -> RunState:
    return store.create(
        task, budget_tokens=budget, max_depth=max_depth, max_concurrency=max_concurrency
    )


def calls_for(client: RecordingClient, role: str) -> list[dict[str, Any]]:
    return [call for call in client.calls if call["role"] == role]


def mock_settings(base: Any, **overrides: Any) -> Any:
    """Copy settings with a fake provider so no real credentials are read by tests."""
    from dataclasses import replace

    from app.config import ProviderConfig

    provider = ProviderConfig(
        base_url="http://fake.local/v1",
        api_key="test-key-not-real",
        model_main="fake-main",
        model_sub="fake-sub",
    )
    defaults = {
        "provider": provider,
        "fallback": None,
        "max_retries": 0,
        "retry_backoff_s": 0.0,
        "delay_ms": 0,
        "failure_inject_mode": "off",
        "thinking_main": False,
        "thinking_sub": False,
        "max_concurrency": 3,
        "breaker_fail_threshold": 99,
        "breaker_cooldown_s": 30.0,
    }
    defaults.update(overrides)
    return replace(base, **defaults)


def llm_result_json(
    *,
    content: str = "",
    reasoning_content: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "model": "fake-model",
        "choices": [
            {
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def tool_call_json(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"call_{uuid4().hex[:8]}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


__all__ = [
    "LlmClient",
    "RecordingClient",
    "calls_for",
    "last_payload",
    "last_payloads",
    "llm_result_json",
    "make_run",
    "mock_settings",
    "result",
    "tool",
    "tool_call_json",
    "tool_result_count",
]