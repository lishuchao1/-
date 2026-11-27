# Super-Agent Orchestration Demo

A run-time orchestrator: one supervisor agent decomposes a task and dispatches sub-agents with
`spawn_agent(role, task, context)`. Each sub-agent has its own context and tool set and returns only
its conclusion. The supervisor merges results; a reviewer sub-agent can reject a draft and send it
back for one revision round.

Backend: Python 3.12 + FastAPI + httpx (async). Frontend: Vite + TypeScript + React. Realtime: SSE.

## What is implemented

- [x] Supervisor plans at run time through tool calls; no hardcoded pipeline
- [x] Isolated sub-agents (`writer`, `marketing`, `reviewer`) with role-scoped tools and artifacts
- [x] Parallel dispatch, depth cap, agent cap and duplicate-task reuse
- [x] Token budget ledger with reservations, soft limit and hard stop
- [x] Reviewer verdict events, revision cap and a finish gate (`skip_review` escape hatch)
- [x] Error taxonomy, retries, circuit breaker, fallback provider, stall watchdog
- [x] Cancellation and durable checkpoints; resume without re-running finished agents
- [x] Run event stream with snapshot and `Last-Event-ID` replay
- [x] Dashboard: agent tree, budget bar, artifacts, transcript, final answer, fault injection
- [x] Offline pytest suite (fake model, 38 tests)

## Reading order

1. `README.md` (this file) - scope, how to run, assumptions
2. `docs/design.md` - architecture, orchestration rules, trade-offs (Chinese)
3. `backend/app/orchestrator.py` - supervisor loop, budget ledger, review gate
4. `backend/app/llm.py` - provider client, error taxonomy, retries, breaker
5. `frontend/src/` - tree view, transcript, budget bar, fault control

## Repository layout

```
backend/app/      FastAPI app, LLM client, orchestrator, tools, event store
backend/tests/    pytest suite (fake LLM by default)
frontend/src/     Vite + TypeScript UI
docs/             design notes
ai-logs/          exported AI sessions and usage heatmap
dev.py            one command to start backend and frontend
```

## How to run

Prerequisites: Python 3.12, Node.js 18+.

```
python -m pip install -r backend/requirements.txt
npm install --prefix frontend
copy .env.example .env        # then fill in your provider values
python dev.py
```

`dev.py` starts uvicorn on `127.0.0.1:8000` and Vite on `127.0.0.1:5173`, after checking that both
ports are free. Open `http://127.0.0.1:5173/`.

Two processes on purpose: the backend never serves the frontend bundle, and the frontend talks to the
API through Vite's dev server.

## Configuration

All settings live in `.env` (git-ignored). `.env.example` lists every key with safe defaults. The
important ones:

| Key | Meaning |
| --- | --- |
| `LLM_BASE_URL`, `LLM_API_KEY` | OpenAI-compatible provider endpoint and key |
| `LLM_MODEL_MAIN`, `LLM_MODEL_SUB` | supervisor model, sub-agent model |
| `LLM_MODEL_ROLE_*` | optional per-role model overrides |
| `PRICE_*_PER_MTOK` | CNY per million tokens, used for cost accounting |
| `RUN_DEFAULT_BUDGET_TOKENS` | default per-run token budget |
| `RUN_BUDGET_RESERVE_TOKENS` | reservation granted to each spawned sub-agent |
| `RUN_DEFAULT_MAX_DEPTH`, `RUN_DEFAULT_MAX_CONCURRENCY` | default run limits |
| `FAILURE_INJECT_MODE` | demo fault injection: `off`, `transient`, `permanent`, `structural`, `task` |
| `RUN_STATE_DIR` | checkpoint directory (git-ignored) |

Secrets never enter the repository or the logs: `.env` is ignored, the API surface never echoes the
key, and the exported AI session logs contain only `[REDACTED]` where a key was typed.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | provider, models, fault-injection mode, uptime |
| POST | `/api/runs` | create a run (`task`, optional `budget_tokens`, `max_depth`, `max_concurrency`) |
| GET | `/api/runs` | list recent runs |
| GET | `/api/runs/{id}` | full public run state |
| GET | `/api/runs/{id}/stream` | SSE: snapshot, replay after `Last-Event-ID`, live tail, final snapshot |
| POST | `/api/runs/{id}/cancel` | cancel a queued/running run |
| POST | `/api/runs/{id}/resume` | resume with `extra_budget_tokens`; finished agents are reused |
| PATCH | `/api/runs/{id}/debug` | update budget/depth/concurrency on a non-terminal run |
| GET/POST | `/api/debug/failures` | read or set demo fault injection (`mode`, optional `calls`) |
| GET | `/api/tick` | SSE demo stream with sequence and replay |

## Failure injection

Set the mode from the UI sidebar or `POST /api/debug/failures`:

- `transient`: one injected retryable failure, then recovery.
- `permanent`: every model attempt fails (bounded by retries, then the breaker).
- `structural`: a structural 400 on the first attempt; no retry, agent becomes `config_error`.
- `task`: one task-level 400; the client narrows the payload and retries once.
- `calls`: how many attempts are affected; empty means the mode default (unlimited for `permanent`).

Injection uses the same error taxonomy as real transport failures, so retry, breaker and fallback
paths are exercised without touching the provider. It spends no tokens.

## Tests

```
python -m pytest backend/tests -q
```

The suite is fully offline (scripted fake model): budget ledger invariants, soft/hard limits,
depth-scoped tools, dedupe, cancellation, agent cap, context isolation, token reconciliation,
reservation exhaustion, artifact ownership, the review gate, unknown tools, structural and task
400 handling, reasoning replay, SSE replay/live dedupe, and checkpoint/resume. 38 tests.

## Design notes

- **Budget ledger**: `tokens_used + reserved_tokens + remaining == budget_tokens`. Spawning reserves
  a bucket; each step draws it down; settling refunds the rest. Concurrency can overshoot by at most
  one step per active agent (observed 13,160 with a 10,000 budget and four agents).
- **Error taxonomy**: `retryable`, `connect`, `quota`, `auth`, `task_400`, `structural_400`,
  `breaker_open`. Only retryable/connect retry; quota/auth/connect/retryable/breaker_open may switch
  to the fallback provider; structural 400s stop with `config_error`.
- **Checkpoints and resume**: full run state is written atomically on key events and throttled to 2s
  otherwise. On restart, runs left `queued/running` become `interrupted`. Resume adds budget, clears
  reservations, sends the new supervisor a brief of completed agents, and answers repeated
  role+task spawns from cache instead of calling the model again.
- **Review gate**: `finish` needs a reviewer verdict or an explicit `skip_review(reason)`; the first
  attempt without either is rejected with `review_not_completed`, the second passes with
  `unverified=true`.
- **SSE contract**: the stream always starts with a full snapshot, replays events after
  `Last-Event-ID`, then follows live events, and ends with a final snapshot when the run reaches a
  terminal status. Clients deduplicate by event id.

## Assumptions

- The provider is OpenAI-compatible. Prices used for cost accounting are the provider's published
  rates as of 2026-11-27, peak-hour, cache-miss tier, so reported cost is a conservative upper bound.
- httpx is created with `trust_env=False`: on this machine the system proxy probe returns a malformed
  value and the default client fails before the request is sent.
- Thinking mode is disabled by default to save tokens and simplify replay. When enabled, the
  provider's reasoning field is echoed back; narrowing on a task-level 400 also strips it.
- Sub-agent artifacts are namespaced per role (`writer.*`, `marketing.*`, `reviewer.verdict`); a
  sub-agent cannot write outside its own namespace.

## AI tools used

Qoder Desktop, driving `deepseek-v4-pro` (supervisor) and `deepseek-flash` (sub-agents) through the
DeepSeek API. Exported session logs and the usage heatmap live in `ai-logs/`.