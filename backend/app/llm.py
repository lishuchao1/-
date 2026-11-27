"""Async OpenAI-compatible chat client.

Error classes are part of the public contract: callers decide whether to
retry, downgrade or stop based on `LlmError.kind`, never by string parsing
at the call site.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from .config import ProviderConfig, Settings

logger = logging.getLogger("agent_g.llm")

ErrorKind = Literal[
    "retryable",
    "task_400",
    "structural_400",
    "quota",
    "auth",
    "connect",
]

STRUCTURAL_HINTS = (
    "reasoning_content",
    "tool_calls",
    "tool schema",
    "tools",
    "messages",
    "unknown model",
    "does not exist",
    "invalid model",
)

QUOTA_HINTS = ("insufficient balance", "quota", "arrears", "余额")

FALLBACK_KINDS = frozenset({"quota", "auth", "retryable", "connect"})


class LlmError(Exception):
    def __init__(self, kind: ErrorKind, message: str, status: int | None = None, attempts: int = 1):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.attempts = attempts


def is_retryable(error: LlmError) -> bool:
    return error.kind in ("retryable", "connect")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0


@dataclass
class LlmResult:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str = ""
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0
    model: str = ""
    finish_reason: str = ""

    def assistant_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.reasoning_content:
            message["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in self.tool_calls
            ]
        return message


def _classify_400(body: str) -> ErrorKind:
    lowered = body.lower()
    if any(hint in lowered for hint in STRUCTURAL_HINTS):
        return "structural_400"
    return "task_400"


class LlmClient:
    def __init__(self, cfg: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._cfg = cfg
        self._semaphore = asyncio.Semaphore(cfg.max_concurrency)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(cfg.timeout_s),
            transport=transport,
            trust_env=False,
        )

    async def complete_with_fallback(
        self,
        messages: list[dict[str, Any]],
        *,
        role: str = "main",
        **kwargs: Any,
    ) -> tuple[LlmResult, bool]:
        """Try the primary provider, then the configured fallback on provider-level failure.

        Returns (result, used_fallback). Task-level 400s are never retried on the
        fallback because switching providers cannot fix a malformed request.
        """
        try:
            return await self.complete(messages, role=role, **kwargs), False
        except LlmError as primary_error:
            fallback = self._cfg.fallback
            if fallback is None or primary_error.kind not in FALLBACK_KINDS:
                raise
            logger.warning(
                "primary failed kind=%s status=%s; switching to fallback base_url=%s",
                primary_error.kind, primary_error.status, fallback.base_url,
            )
            try:
                result = await self.complete(messages, role=role, provider=fallback, **kwargs)
            except LlmError as fallback_error:
                raise LlmError(
                    fallback_error.kind,
                    f"primary {primary_error.kind}: {primary_error}; "
                    f"fallback {fallback_error.kind}: {fallback_error}",
                    fallback_error.status,
                    primary_error.attempts + fallback_error.attempts,
                ) from fallback_error
            return result, True

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        role: str = "main",
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        provider: ProviderConfig | None = None,
    ) -> LlmResult:
        cfg = self._cfg
        target = provider or cfg.provider
        model = cfg.model_for(role) if provider is None else (
            provider.model_main if role == "main" else provider.model_sub
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        thinking = cfg.thinking_main if role == "main" else cfg.thinking_sub
        if not thinking:
            payload["thinking"] = {"type": "disabled"}

        url = target.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {target.api_key}",
            "Content-Type": "application/json",
        }

        attempts_allowed = 1 + max(0, cfg.max_retries)
        last_error: LlmError | None = None
        for attempt in range(1, attempts_allowed + 1):
            if cfg.delay_ms:
                await asyncio.sleep(cfg.delay_ms / 1000)
            started = time.perf_counter()
            async with self._semaphore:
                try:
                    response = await self._client.post(url, headers=headers, json=payload)
                except httpx.TimeoutException as exc:
                    last_error = LlmError("retryable", f"timeout: {exc!r}", attempts=attempt)
                except httpx.TransportError as exc:
                    last_error = LlmError("connect", f"transport: {exc!r}", attempts=attempt)
                except asyncio.CancelledError:
                    raise
                else:
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    if response.status_code == 200:
                        return self._parse(response.json(), role, latency_ms)
                    body = response.text[:800]
                    last_error = self._http_error(response.status_code, body, attempt)

            if last_error is not None and is_retryable(last_error) and attempt < attempts_allowed:
                backoff = cfg.retry_backoff_s * attempt
                logger.warning(
                    "retrying model=%s attempt=%s/%s kind=%s status=%s in %.1fs",
                    model, attempt, attempts_allowed, last_error.kind, last_error.status, backoff,
                )
                await asyncio.sleep(backoff)
                continue
            if last_error is not None:
                raise last_error
        raise last_error or LlmError("retryable", "exhausted without result")

    def _http_error(self, status: int, body: str, attempt: int) -> LlmError:
        if status == 400:
            return LlmError(_classify_400(body), f"400: {body}", status, attempt)
        if status in (401, 403):
            return LlmError("auth", f"{status}: {body}", status, attempt)
        if status == 402 or any(hint in body.lower() for hint in QUOTA_HINTS):
            return LlmError("quota", f"{status}: {body}", status, attempt)
        if status == 429 or 500 <= status < 600:
            return LlmError("retryable", f"{status}: {body}", status, attempt)
        return LlmError("task_400", f"{status}: {body}", status, attempt)

    def _parse(self, data: dict[str, Any], role: str, latency_ms: int) -> LlmResult:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls = [
            ToolCall(
                id=item.get("id", ""),
                name=(item.get("function") or {}).get("name", ""),
                arguments=(item.get("function") or {}).get("arguments", "{}"),
            )
            for item in message.get("tool_calls") or []
        ]
        raw_usage = data.get("usage") or {}
        tokens_in = int(raw_usage.get("prompt_tokens") or 0)
        tokens_out = int(raw_usage.get("completion_tokens") or 0)
        price_in, price_out = self._cfg.price_for(role)
        cost = round(tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out, 8)
        usage = Usage(tokens_in=tokens_in, tokens_out=tokens_out, cost=cost)
        result = LlmResult(
            content=str(message.get("content") or ""),
            tool_calls=tool_calls,
            reasoning_content=str(message.get("reasoning_content") or ""),
            usage=usage,
            latency_ms=latency_ms,
            model=str(data.get("model") or ""),
            finish_reason=str(choice.get("finish_reason") or ""),
        )
        logger.info(
            "model=%s role=%s in=%s out=%s cost=%.6f latency_ms=%s finish=%s",
            result.model, role, tokens_in, tokens_out, cost, latency_ms, result.finish_reason,
        )
        return result


def dumps_tool_args(call: ToolCall) -> dict[str, Any]:
    try:
        value = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}