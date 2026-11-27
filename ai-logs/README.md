# AI session logs

## Status: the raw session is not included

The exam asks for the complete, unmodified development session and its tool-call traces. This
submission does not contain that raw session. The reason is:

- The session is the user's private working record. Exporting it means copying the native Qoder
  session JSONL into a public GitHub repository.
- The export was attempted for the single authorized session only. The environment's permission
  policy blocked writing the raw session to the repository (`Sensitive-Source Provenance`), and
  the block could not be lifted without overriding the user's privacy boundary.
- No partial, filtered, summarized or rewritten transcript was committed instead. The exam allows
  exactly one edit, secret redaction; publishing anything less than the whole session would be
  misleading, so nothing was published.
- The parts that can be published without exposing the private session are kept here: the tool and
  model record, the export method, the commit mapping, and the usage heatmap.

中文说明：本次会话包含个人隐私；环境权限策略禁止把原始会话写入公开仓库。未提交会话原文，也没有用
删减版或改写版替代；本目录只保留工具/模型说明、导出方式、提交映射和用量热力图。

## Tool and model

- Tool: Qoder Desktop (standalone app), session id `35e733fb-7cb8-4fad-b6a0-ca5fb4e7c3f7`,
  session format version `1.1.79-hotfix.19`.
- Model: Qoder `auto` routing (session records show `model: auto`).
- The built product calls DeepSeek separately: `deepseek-v4-pro` for the supervisor and
  `deepseek-flash` for sub-agents. That API key never appears in this repository.

## Scope

Only the exam session above is discussed or charted. The workspace has older Qoder sessions from
2026-11-13 to 2026-11-26; they are unrelated preparation history, are not exported, and are not
aggregated into the heatmap.

## Files in this directory

| file | content |
| --- | --- |
| `README.md` | this status note, tool/model record, export method, commit mapping |
| `usage-heatmap/qoder-usage.png` | daily sessions, messages, tool calls and credits with visible dates |
| `usage-heatmap/qoder-usage-90d.png` | 90-day calendar; days outside the authorized export are hatched |
| `usage-heatmap/qoder-usage.csv` | the underlying per-day numbers |

There are no `sessions/` or `transcripts/` files in this submission.

## Export method (documented, not completed)

Qoder stores each chat as newline-delimited JSON at
`%USERPROFILE%\.qoder-cn\projects\E--Qoder-gongzuo\<session-id>.jsonl`.
The offline exporter reads only that one file, copies it whole, and changes nothing except secrets:

```bash
python E:\Qoder\gongzuo\_handoff\export_ai_logs.py --out E:\Qoder\gongzuo\agent-g\ai-logs
```

It would produce `sessions/35e733fb-....jsonl` (authoritative raw records) and
`transcripts/35e733fb-....part-NN.md` (a complete readable rendering, split only for size), then
rewrite this README with the sha256, record counts and final commit list. The exporter is
fail-closed: if a known secret pattern survives redaction it aborts instead of writing a partial
export.

## Redaction policy

The exam permits exactly one kind of edit: replacing secrets with `[REDACTED]`. The exporter
replaces exact values from `agent-g/.env` whose variable names contain KEY / TOKEN / SECRET /
PASSWORD, plus recognizable key formats (`sk-...`, `ghp_...`, `github_pat_...`, `xox...`,
`AIza...`) and PEM private-key blocks. Placeholders such as `your-key-here` are left unchanged.
No API key is stored in this repository: `agent-g/.env` is gitignored and
`agent-g/.env.example` contains placeholders only.

## Session to commit mapping

Every commit below was produced inside the included session. Times are local (UTC+8).

Phases:

- 10:07–11:23 — backend core: state models, LLM client and error taxonomy, provider fallback,
  tool loop, supervisor with isolated sub-agents, budget ledger, circuit breaker, artifact
  ownership, duplicate-dispatch guard.
- 11:30–11:54 — resilience and review: failure injection, cancellation, checkpoints and resume,
  SSE replay, review gate and revision cap, dashboard, offline scripted-model tests, live debug
  patching, design document.
- 12:16–12:26 — conversation visibility: per-agent transcripts and tool lists, missing-slot
  markers, context truncation marker, bounded-overshoot label, README.
- 12:43–12:44 — usage heatmap and this documentation.
- The final `ai-logs/` commit adds the status note above; no session data is added.

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
| `82cf5ad` | 2026-11-27 12:44 | document the ai-logs export method and commit mapping |

## Usage heatmap

The charts cover the authorized session only, on 2026-11-27: 1 session, 11 human messages,
836 assistant records, 830 tool calls and 269.08 credits. The session records carry `usage.credits`
but zero token counters, so credits are charted instead of estimated tokens.

The exam asks for at least three months, or all available history. The only history the user
authorized is this session, so the chart shows exactly that window and hatches the remaining days
as `outside the authorized export` rather than drawing them as zero. This is a deliberate privacy
tradeoff, not missing data. Nothing is cropped, retouched or estimated; `qoder-usage.csv` holds the
same numbers.

## How the export would be read

If an authorized export is produced later, the JSONL is authoritative:

```bash
jq -r 'select(.type=="user") | .message.content[]? | select(.type=="text") | .text' sessions/*.jsonl
jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use") | [.name, (.input|tostring)] | @tsv' sessions/*.jsonl
```

Tool results are `user` records containing `tool_result` blocks keyed by `tool_use_id`. The
transcripts would preserve the original order and include thinking blocks, so the whole session
could be read without parsing JSON.

Documented on 2026-11-27 (UTC+8).