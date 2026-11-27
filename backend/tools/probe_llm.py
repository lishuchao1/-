"""Manual connectivity and contract probes against the configured provider.

Usage:
    python -m tools.probe_llm plain
    python -m tools.probe_llm tools

Run from the backend directory. Never prints the API key.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.llm import LlmClient, LlmError, dumps_tool_args  # noqa: E402

TOOL = [
    {
        "type": "function",
        "function": {
            "name": "echo_note",
            "description": "Record a short note.",
            "parameters": {
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "required": ["note"],
            },
        },
    }
]


async def plain() -> int:
    client = LlmClient(settings)
    try:
        result = await client.complete(
            [{"role": "user", "content": "Reply with the single word: pong"}],
            role="main",
            max_tokens=16,
        )
        print(f"content={result.content.strip()!r}")
        print(f"model={result.model} finish={result.finish_reason}")
        print(f"tokens_in={result.usage.tokens_in} tokens_out={result.usage.tokens_out} cost={result.usage.cost}")
        print(f"reasoning_len={len(result.reasoning_content)} latency_ms={result.latency_ms}")
        return 0
    except LlmError as error:
        print(f"llm_error kind={error.kind} status={error.status} message={str(error)[:200]}")
        return 2
    finally:
        await client.aclose()


async def tools() -> int:
    client = LlmClient(settings)
    messages: list[dict[str, object]] = [
        {
            "role": "user",
            "content": "Call echo_note once with note='roundtrip-ok'. Do not answer in text.",
        }
    ]
    try:
        first = await client.complete(messages, role="main", tools=TOOL, max_tokens=64)
        print(f"first_tool_calls={[(c.name, c.arguments) for c in first.tool_calls]}")
        print(f"first_reasoning_len={len(first.reasoning_content)} finish={first.finish_reason}")
        if not first.tool_calls:
            print("no tool call returned")
            return 2
        call = first.tool_calls[0]
        print(f"parsed_args={json.dumps(dumps_tool_args(call))}")
        messages.append(first.assistant_message())
        messages.append(
            {"role": "tool", "tool_call_id": call.id, "content": json.dumps({"ok": True})}
        )
        second = await client.complete(messages, role="main", tools=TOOL, max_tokens=64)
        print(f"second_content={second.content.strip()[:120]!r}")
        print(f"second_finish={second.finish_reason} second_tool_calls={len(second.tool_calls)}")
        return 0
    except LlmError as error:
        print(f"llm_error kind={error.kind} status={error.status} message={str(error)[:300]}")
        return 2
    finally:
        await client.aclose()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "plain"
    if mode == "plain":
        return asyncio.run(plain())
    if mode == "tools":
        return asyncio.run(tools())
    print(f"unknown mode: {mode}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())