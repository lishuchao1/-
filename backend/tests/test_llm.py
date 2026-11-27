"""Provider client behavior: concurrency cap, retry classes, reasoning replay.

T4  configurable concurrency ceiling holds.
T6a non-retryable structural 400 makes exactly one HTTP call.
T6a-narrow task-level 400 retries once with reasoning fields stripped.
T6b retryable 500 makes exactly two HTTP calls when max_retries=1.
T11 reasoning_content is replayed verbatim on the second round trip.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.config import settings
from app.llm import LlmClient, LlmError
from app.tool_loop import ToolSpec, run_tool_loop
from tests.fakes import llm_result_json, mock_settings, tool_call_json


async def _ok_handler(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=llm_result_json(content="hello"))


async def test_concurrency_cap_is_respected() -> None:
    active = 0
    peak = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.05)
            return httpx.Response(200, json=llm_result_json(content="ok"))
        finally:
            active -= 1

    cfg = mock_settings(settings, max_concurrency=1)
    client = LlmClient(cfg, transport=httpx.MockTransport(handler))
    try:
        await asyncio.gather(
            *[client.complete([{"role": "user", "content": f"q{i}"}]) for i in range(3)]
        )
    finally:
        await client.aclose()
    assert peak == 1


async def test_structural_400_is_not_retried() -> None:
    requests: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            400, json={"error": {"message": "messages rejected: reasoning_content not allowed"}}
        )

    cfg = mock_settings(settings, max_retries=2)
    client = LlmClient(cfg, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(LlmError) as caught:
            await client.complete([{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()
    assert caught.value.kind == "structural_400"
    assert len(requests) == 1


async def test_task_400_narrows_once_then_gives_up() -> None:
    requests: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"message": "upstream rejected the request"}})

    cfg = mock_settings(settings, max_retries=2)
    client = LlmClient(cfg, transport=httpx.MockTransport(handler))
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "", "reasoning_content": "private thoughts"},
        {"role": "tool", "tool_call_id": "call_1", "content": "{}"},
        {"role": "user", "content": "continue"},
    ]
    try:
        with pytest.raises(LlmError) as caught:
            await client.complete(messages)
    finally:
        await client.aclose()
    assert caught.value.kind == "task_400"
    assert len(requests) == 2
    assert client.narrow_retries == 1
    assert requests[0]["messages"][1]["reasoning_content"] == "private thoughts"
    assert "reasoning_content" not in requests[1]["messages"][1]
    assert requests[1]["thinking"] == {"type": "disabled"}


async def test_retryable_500_retries_exactly_once() -> None:
    requests: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(500, json={"error": {"message": "upstream exploded"}})

    cfg = mock_settings(settings, max_retries=1)
    client = LlmClient(cfg, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(LlmError) as caught:
            await client.complete([{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()
    assert caught.value.kind == "retryable"
    assert len(requests) == 2


async def test_reasoning_content_is_replayed_on_next_round() -> None:
    bodies: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(
                200,
                json=llm_result_json(
                    reasoning_content="step one reasoning",
                    tool_calls=[tool_call_json("write", {"key": "value"})],
                ),
            )
        return httpx.Response(200, json=llm_result_json(content="done"))

    cfg = mock_settings(settings, max_retries=0)
    client = LlmClient(cfg, transport=httpx.MockTransport(handler))
    tools = {
        "write": ToolSpec(
            {"type": "function", "function": {"name": "write", "parameters": {"type": "object"}}},
            lambda args: {"ok": True},
        )
    }
    try:
        loop = await run_tool_loop(
            client,
            role="main",
            messages=[{"role": "user", "content": "go"}],
            tools=tools,
            max_steps=3,
        )
    finally:
        await client.aclose()
    assert loop.stop_reason == "stop"
    assert len(bodies) == 2
    replayed = [m for m in bodies[1]["messages"] if m.get("role") == "assistant"]
    assert replayed and replayed[0]["reasoning_content"] == "step one reasoning"


def test_health_payload_shape() -> None:
    """Cheap sanity check that the mock settings helper stays usable."""
    cfg = mock_settings(settings)
    assert cfg.provider.api_key == "test-key-not-real"
    assert cfg.fallback is None