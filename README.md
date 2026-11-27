# Super-Agent Orchestration Demo

A run-time orchestrator: one supervisor agent decomposes a task and dispatches sub-agents with
`spawn_agent(role, task, context)`. Each sub-agent has its own context and tool set and returns only
its conclusion. The supervisor merges results, and a reviewer sub-agent can reject a draft and send
it back for one revision round.

Backend: Python 3.12 + FastAPI + httpx (async). Frontend: Vite + TypeScript + React. Realtime: SSE.

## Status

This repository is being built in small, sequential commits. Current state:

- [x] Project scope and plan
- [ ] Backend skeleton with `/health`
- [ ] Frontend skeleton and one-command dev launcher
- [ ] SSE sequence stream
- [ ] LLM client with concurrency limit and cost accounting
- [ ] Tool-calling round trip
- [ ] Run/agent model and store
- [ ] Orchestrator with dynamic `spawn_agent`
- [ ] Budget, depth, concurrency and duplicate-dispatch guards
- [ ] Artifact store with role ownership
- [ ] Failure injection, cancellation, retry policy
- [ ] Run event stream with replay
- [ ] Agent tree view and final answer panel
- [ ] Reviewer verdict and revision flow
- [ ] Orchestrator tests with a fake LLM
- [ ] Design doc

## Reading order

1. `README.md` (this file) - scope, how to run, assumptions
2. `docs/design.md` - architecture, orchestration rules, trade-offs
3. `backend/app/orchestrator.py` - the supervisor loop and sub-agent executor
4. `backend/app/llm.py` - provider client, cost accounting, retry classification
5. `frontend/src/` - tree view, transcript panel, debug panel

## Repository layout

```
backend/app/      FastAPI app, LLM client, orchestrator, tools, event store
backend/tests/    pytest suite (fake LLM by default)
frontend/src/     Vite + TypeScript UI
docs/             design notes and probe results
ai-logs/          exported AI sessions and usage heatmap
dev.py            one command to start backend and frontend
```

## How to run

Planned entry point, to be filled in as the pieces land:

```
python -m pip install -r backend/requirements.txt
python dev.py
```

`dev.py` starts uvicorn and the Vite dev server, and checks that both ports are free first.

## Tests

```
python -m pytest backend/tests
```

The suite uses a fake LLM client, so it runs without an API key. Tests that call a real provider are
marked `live` and skipped by default.

## Configuration

Copy `.env.example` to `.env` and fill in your own values. `.env` is git-ignored and never committed.

## AI tools used

Qoder Desktop, driving the provider models `deepseek-v4-pro` (supervisor) and `deepseek-flash`
(sub-agents). Exported session logs live in `ai-logs/` together with a usage heatmap.

## Assumptions

- The provider is OpenAI-compatible. Prices used for cost accounting are the provider's published
  rates as of 2026-11-27, peak-hour, cache-miss tier, so reported cost is a conservative upper bound.
- httpx is created with `trust_env=False`: on this machine the system proxy probe returns a malformed
  value and the default client fails before the request is sent.
- Thinking mode is disabled by default. If it is enabled, every follow-up turn must echo the
  provider's reasoning field back, otherwise the provider answers 400.
- Budget accounting reserves tokens per sub-agent before it starts, settles after it finishes, and
  returns the unused part. Reported token totals therefore stay within the run budget.
- Artifacts are namespaced per role (`writer.*`, `marketing.*`, `reviewer.verdict`); a sub-agent
  cannot write outside its own namespace.