"""Model-driven tool loop shared by the supervisor and every sub-agent.

The loop owns the provider round trip, tool dispatch and usage accounting.
Handlers are plain callables; unknown tools and malformed arguments become
structured tool messages instead of crashing the run.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .llm import LlmClient, LlmError, LlmResult, Usage

logger = logging.getLogger("agent_g.loop")

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


@dataclass
class ToolSpec:
    schema: dict[str, Any]
    handler: ToolHandler


@dataclass
class StepRecord:
    index: int
    tools: list[dict[str, Any]] = field(default_factory=list)
    content: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    invalid_tool: str = ""


@dataclass
class LoopResult:
    content: str
    steps: list[StepRecord]
    usage: Usage
    finished: bool
    stop_reason: str


async def run_tool_loop(
    client: LlmClient,
    *,
    role: str,
    messages: list[dict[str, Any]],
    tools: dict[str, ToolSpec],
    max_steps: int = 6,
    max_tokens: int | None = 900,
    terminal_tools: frozenset[str] = frozenset(),
    parallel_tools: frozenset[str] = frozenset(),
    budget_guard: Callable[[], bool] | None = None,
    on_step: Callable[[StepRecord], None] | None = None,
    on_tool: Callable[[str, str, dict[str, Any], str], None] | None = None,
) -> LoopResult:
    total = Usage()
    steps: list[StepRecord] = []
    schemas = [spec.schema for spec in tools.values()]
    content = ""
    finished = False
    stop_reason = "max_steps"
    consecutive_invalid = 0

    for index in range(max_steps):
        if budget_guard is not None and not budget_guard():
            stop_reason = "budget_exhausted"
            content = content or "stopped: token budget exhausted"
            break
        result: LlmResult = await client.complete(
            messages,
            role=role,
            tools=schemas or None,
            max_tokens=max_tokens,
        )
        total.tokens_in += result.usage.tokens_in
        total.tokens_out += result.usage.tokens_out
        total.cost = round(total.cost + result.usage.cost, 8)
        content = result.content
        record = StepRecord(
            index=index,
            content=result.content[:500],
            tokens_in=result.usage.tokens_in,
            tokens_out=result.usage.tokens_out,
            latency_ms=result.latency_ms,
        )

        if not result.tool_calls:
            finished = True
            stop_reason = "stop" if result.finish_reason in ("stop", "length") else result.finish_reason
            steps.append(record)
            if on_step:
                on_step(record)
            break

        messages.append(result.assistant_message())
        calls = list(result.tool_calls)
        terminal = False

        def handle(call: Any, payload: dict[str, Any], invalid: str) -> None:
            nonlocal terminal, consecutive_invalid
            record.tools.append({"name": call.name, "arguments": call.arguments[:300]})
            if invalid:
                record.invalid_tool = invalid
                consecutive_invalid += 1
                if invalid == "invalid_arguments" and result.finish_reason == "length":
                    payload = {
                        "error": "invalid_arguments",
                        "detail": (
                            "arguments were cut off because the reply hit max_tokens; "
                            "shorten the content field and call the tool again"
                        ),
                    }
            else:
                consecutive_invalid = 0
            if on_tool:
                on_tool(call.name, call.arguments, payload, invalid)
            if call.name in terminal_tools:
                terminal = True
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(payload, ensure_ascii=False),
                }
            )

        fan_out = len(calls) > 1 and all(call.name in parallel_tools for call in calls)
        if fan_out:
            outcomes = await asyncio.gather(
                *[_dispatch(tools, call.name, call.arguments) for call in calls]
            )
            for call, (payload, invalid) in zip(calls, outcomes):
                handle(call, payload, invalid)
        else:
            for call in calls:
                payload, invalid = await _dispatch(tools, call.name, call.arguments)
                handle(call, payload, invalid)
        steps.append(record)
        if on_step:
            on_step(record)
        if terminal:
            finished = True
            stop_reason = "finished_tool"
            break
        if consecutive_invalid >= 2:
            content = "stuck: repeated invalid tool arguments; last response was not usable"
            stop_reason = "stuck_invalid_tools"
            logger.warning("stopping loop role=%s after repeated invalid tool calls", role)
            break

    return LoopResult(
        content=content,
        steps=steps,
        usage=total,
        finished=finished,
        stop_reason=stop_reason,
    )


async def _dispatch(
    tools: dict[str, ToolSpec], name: str, raw_arguments: str
) -> tuple[dict[str, Any], str]:
    spec = tools.get(name)
    if spec is None:
        logger.warning("invalid_tool_call name=%s", name)
        return {"error": "unknown_tool", "tool": name}, "unknown_tool"
    try:
        arguments = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError:
        logger.warning("invalid_tool_call name=%s reason=bad_json", name)
        return {"error": "invalid_arguments", "detail": "arguments are not valid JSON"}, "invalid_arguments"
    if not isinstance(arguments, dict):
        return {"error": "invalid_arguments", "detail": "arguments must be an object"}, "invalid_arguments"
    try:
        value = spec.handler(arguments)
        if inspect.isawaitable(value):
            value = await value
    except LlmError:
        raise
    except Exception as exc:  # tool bugs must not kill the whole run
        logger.exception("tool_failed name=%s", name)
        return {"error": "tool_failed", "detail": str(exc)[:300]}, "tool_failed"
    return value if isinstance(value, dict) else {"result": value}, ""