# AI session logs

This directory is the exam's `ai-logs/` deliverable: the complete, unmodified development session
for this task, exported from the AI tool's native session store, plus a usage heatmap.

## Tool and model

- Tool: Qoder Desktop (standalone app), session format version `1.1.79-hotfix.19`.
- Model: Qoder `auto` routing (the session records show `model: auto`). The built product calls
  DeepSeek separately with its own API key; that key never appears in this directory.
- The session id is `35e733fb-7cb8-4fad-b6a0-ca5fb4e7c3f7`; its working directory is
  `E:\Qoder\gongzuo` and its first message is `2026-11-27 09:55:18 +08:00`.

## Scope: this session only

Only the session above is included anywhere in this directory. The workspace has older Qoder
sessions from 2026-11-13 to 2026-11-26; they are unrelated preparation history and are excluded,
per the user's instruction. No data from any other AI tool is included.

## Files and how each is exported

| file | content | export method |
| --- | --- | --- |
| `sessions/35e733fb-7cb8-4fad-b6a0-ca5fb4e7c3f7.jsonl` | raw session, one JSON record per line | byte-for-byte copy of the tool's native JSONL, with only secret values replaced by `[REDACTED]` |
| `transcripts/35e733fb-7cb8-4fad-b6a0-ca5fb4e7c3f7.part-NN.md` | complete readable rendering of every record: prompts, replies, thinking, tool calls, tool results, in order | rendered from the same JSONL; split into ~400k-character parts only because of file size |
| `transcripts/35e733fb-7cb8-4fad-b6a0-ca5fb4e7c3f7.index.md` | part boundaries and record ranges | generated with the transcripts |
| `usage-heatmap/qoder-usage.png` | per-day sessions, messages, tool calls and credits with visible dates | charted from this session's records |
| `usage-heatmap/qoder-usage-90d.png` | 90-day calendar view; days outside the authorized export are hatched | charted from this session's records |
| `usage-heatmap/qoder-usage.csv` | the underlying per-day numbers | charted from this session's records |

Qoder stores each chat as newline-delimited JSON at
`%USERPROFILE%\.qoder-cn\projects\E--Qoder-gongzuo\<session-id>.jsonl`.
The exporter reads only that one file, copies it whole, and changes nothing except secrets.
The Markdown transcripts are a convenience rendering; the JSONL is authoritative and keeps every
raw field.

Exporter command (kept outside the repository so the repository only contains the result):

```bash
python E:\Qoder\gongzuo\_handoff\export_ai_logs.py --out E:\Qoder\gongzuo\agent-g\ai-logs
```

The exporter is fail-closed: if any known secret pattern survives redaction it aborts instead of
writing a partial export.

## Redaction

The exam permits exactly one kind of edit: replacing secrets with `[REDACTED]`. The exporter
replaces:

- exact values from `agent-g/.env` whose variable names contain KEY / TOKEN / SECRET / PASSWORD;
- recognizable key formats: `sk-...`, `ghp_...`, `github_pat_...`, `xox...`, `AIza...`, and PEM
  private-key blocks.

Placeholders such as `your-key-here` in `.env.example` are left unchanged. The exporter prints the
per-pattern replacement counts when it runs. No API key, token or password is stored in this
repository: `agent-g/.env` is gitignored and `agent-g/.env.example` contains placeholders only.

## Session to commit mapping

Every commit below was produced inside the included session; the transcript therefore covers the
work end to end. Times are local (UTC+8).

Phases:

- 10:07–11:23 — backend core: state models, LLM client and error taxonomy, provider fallback,
  tool loop, supervisor with isolated sub-agents, budget ledger, circuit breaker, artifact
  ownership, duplicate-dispatch guard.
- 11:30–11:54 — resilience and review: failure injection, cancellation, checkpoints and resume,
  SSE replay, review gate and revision cap, dashboard, offline scripted-model tests, live debug
  patching, design document.
- 12:16–12:26 — conversation visibility: per-agent transcripts and tool lists, missing-slot
  markers, context truncation marker, bounded-overshoot label, README.
- 12:43 and the final `ai-logs/` commit — the heatmap and this export.

| commit | time | subject |
| --- | --- | --- |
| `8e86e37` | 2026-11-27 10:07 | Initial commit |
| `354c0df` | 2026-11-27 10:51 | add project README with scope and run plan |
| `c7d2185` | 2026-11-27 10:56 | add FastAPI backend skeleton with health endpoint |
| `323f6c6` | 2026-11-27 11:00 | add Vite TypeScript frontend and one-command dev launcher |
| `72fdde2` | 2026-11-27 11:03 | add SSE tick stream with Last-Event-ID replay and tick panel |
| `a364a66` | 2026-11-27 11:04 | add async LLM client with error taxonomy, retries and cost accounting |
| `272c080` | 2026-11-27 11:05 | add provider fallback path for quota and connectivity failures |
| `10c7ed9` | 2026-11-27 11:05 | add model-driven tool loop with invalid call handling |
| `24b15b3` | 2026-11-27 11:06 | add run and agent state models with event store |
| `6aea456` | 2026-11-27 11:16 | add supervisor runtime with spawn_agent and isolated sub-agents |
| `f55fbc8` | 2026-11-27 11:17 | dispatch sibling spawn calls concurrently |
| `2bc7312` | 2026-11-27 11:19 | add token budget ledger with reservations and hard stop |
| `e24b43b` | 2026-11-27 11:21 | add provider circuit breaker and stall watchdog |
| `57b34bd` | 2026-11-27 11:22 | prevent duplicate sub-agent dispatch by role and task |
| `6daf7ad` | 2026-11-27 11:23 | track last writer per artifact and test ownership rules |
| `ebfbdb8` | 2026-11-27 11:30 | add failure injection, classified retries and run cancellation |
| `aa1b5b4` | 2026-11-27 11:36 | persist run checkpoints to disk and resume without re-running finished agents |
| `23fccb4` | 2026-11-27 11:37 | stream run events with snapshot and Last-Event-ID replay |
| `1b37465` | 2026-11-27 11:43 | record review verdicts and enforce finish and revision limits |
| `a1eb425` | 2026-11-27 11:43 | add live run dashboard with agent tree budget and transcript |
| `e2e715c` | 2026-11-27 11:49 | require review or explicit skip before a run can finish |
| `fe559b7` | 2026-11-27 11:50 | cover orchestration invariants with an offline scripted model suite |
| `e64a927` | 2026-11-27 11:54 | allow live debug patching and failing the next spawned agent |
| `6550c73` | 2026-11-27 11:54 | document the orchestration design and configuration surface |
| `f3fe804` | 2026-11-27 12:16 | expose the exact conversation each agent saw from the tree view |
| `b422ef8` | 2026-11-27 12:17 | mark required artifact slots as missing on terminal runs |
| `9fca79c` | 2026-11-27 12:21 | truncate oversized supervisor context with an explicit marker |
| `15ca7ef` | 2026-11-27 12:22 | label bounded budget overshoot from in-flight steps |
| `71e71f7` | 2026-11-27 12:25 | show each agent's tool list next to its conversation |
| `2320188` | 2026-11-27 12:26 | document the agent prompts roles and demo walkthrough |
| `635f02d` | 2026-11-27 12:43 | add usage heatmap for the authorized exam session |

This README and the exported session are added by the final `ai-logs/`-only commits; the exam
allows the last of those to land up to 30 minutes after the deadline.

## Usage heatmap

The charts cover the authorized session only, on 2026-11-27: 1 session, 11 human messages,
836 assistant records, 830 tool calls and 269.08 credits. The session records carry `usage.credits`
but zero token counters, so credits are charted instead of estimated tokens.

The exam asks for at least three months, or all available history. The only history the user
authorized for export is this session, so the heatmap shows exactly that window and hatches the
remaining days as `outside the authorized export` rather than drawing them as zero. Nothing is
cropped, retouched or estimated; `qoder-usage.csv` holds the same numbers.

## How to read the JSONL

```bash
jq -r 'select(.type=="user") | .message.content[]? | select(.type=="text") | .text' sessions/*.jsonl
jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use") | [.name, (.input|tostring)] | @tsv' sessions/*.jsonl
```

Tool results are `user` records containing `tool_result` blocks keyed by `tool_use_id`. The
transcripts preserve the original order and include thinking blocks, so the whole session can be
read without parsing JSON.

Documented on 2026-11-27 (UTC+8). The exporter regenerates this file with the exported session's
sha256, record counts and final commit list when it runs.