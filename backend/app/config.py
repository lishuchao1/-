"""Settings loaded from environment with a repo-root .env fallback.

Values are read once at import time. Secrets never leave this process and are
never logged by the application.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_str(name) or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_str(name) or default)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = _str(name, "1" if default else "0").lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    api_key: str
    model_main: str
    model_sub: str


@dataclass(frozen=True)
class Settings:
    provider: ProviderConfig
    fallback: ProviderConfig | None
    timeout_s: float
    max_retries: int
    retry_backoff_s: float
    delay_ms: int
    thinking_main: bool
    thinking_sub: bool
    price: dict[str, tuple[float, float]]
    budget_tokens: int
    budget_reserve_tokens: int
    max_depth: int
    max_concurrency: int
    context_max_chars: int
    failure_inject_mode: str
    breaker_fail_threshold: int
    breaker_cooldown_s: float
    stall_timeout_s: float
    state_dir: Path
    role_models: dict[str, str] = field(default_factory=dict)

    def model_for(self, role: str) -> str:
        if role in self.role_models and self.role_models[role]:
            return self.role_models[role]
        return self.provider.model_main if role == "main" else self.provider.model_sub

    def price_for(self, role: str) -> tuple[float, float]:
        key = "main" if role == "main" else "sub"
        return self.price.get(key, (0.0, 0.0))


def _provider(prefix: str) -> ProviderConfig:
    return ProviderConfig(
        base_url=_str(f"{prefix}BASE_URL").rstrip("/"),
        api_key=_str(f"{prefix}API_KEY"),
        model_main=_str(f"{prefix}MODEL_MAIN"),
        model_sub=_str(f"{prefix}MODEL_SUB"),
    )


def load_settings() -> Settings:
    primary = _provider("LLM_")
    fallback = _provider("LLM_FALLBACK_")
    if not fallback.base_url or not fallback.api_key:
        fallback = None
    elif not fallback.model_main:
        fallback = None
    return Settings(
        provider=primary,
        fallback=fallback,
        timeout_s=_float("LLM_TIMEOUT_S", 90.0),
        max_retries=_int("LLM_MAX_RETRIES", 2),
        retry_backoff_s=_float("LLM_RETRY_BACKOFF_S", 2.0),
        delay_ms=_int("LLM_DELAY_MS", 0),
        thinking_main=_bool("THINKING_MAIN", False),
        thinking_sub=_bool("THINKING_SUB", False),
        price={
            "main": (
                _float("PRICE_MAIN_IN_PER_MTOK", 0.0),
                _float("PRICE_MAIN_OUT_PER_MTOK", 0.0),
            ),
            "sub": (
                _float("PRICE_SUB_IN_PER_MTOK", 0.0),
                _float("PRICE_SUB_OUT_PER_MTOK", 0.0),
            ),
        },
        budget_tokens=_int("RUN_DEFAULT_BUDGET_TOKENS", 200_000),
        budget_reserve_tokens=_int("RUN_BUDGET_RESERVE_TOKENS", 3_000),
        max_depth=_int("RUN_DEFAULT_MAX_DEPTH", 2),
        max_concurrency=_int("RUN_DEFAULT_MAX_CONCURRENCY", 3),
        context_max_chars=_int("CONTEXT_MAX_CHARS", 2_000),
        failure_inject_mode=_str("FAILURE_INJECT_MODE", "transient"),
        breaker_fail_threshold=_int("BREAKER_FAIL_THRESHOLD", 3),
        breaker_cooldown_s=_float("BREAKER_COOLDOWN_S", 30.0),
        stall_timeout_s=_float("RUN_STALL_TIMEOUT_S", 180.0),
        state_dir=(ROOT / _str("RUN_STATE_DIR", "runs")),
        role_models={
            role: _str(f"LLM_MODEL_ROLE_{role.upper()}")
            for role in ("writer", "reviewer", "marketing")
        },
    )


settings = load_settings()