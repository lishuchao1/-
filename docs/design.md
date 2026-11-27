# 架构与设计说明

本文描述这套 Super-Agent 编排演示的内部结构、关键不变量与取舍。代码标识符一律英文；本文用中文解释。

## 1. 目标与边界

- 一个 supervisor agent 在**运行期**决定派哪些子 agent、顺序与上下文；没有硬编码流水线。
- 子 agent 相互隔离：只能看到自己的 system prompt、任务、supervisor 给的 context，以及自己的工具往返。
- 子 agent 的产出通过 **artifact**（命名空间为 `writer.*` / `marketing.*` / `reviewer.verdict`）回到 supervisor，而不是原始对话。
- 前端展示：agent 树、预算条、artifact 认领表、事件转录、最终答案、故障注入与调试信息。

不做的事情：持久数据库、多租户、鉴权、向量检索、真正的多机调度。单进程内存态 + 磁盘 checkpoint 足以支撑演示与断点续跑。

## 2. 组件

| 模块 | 职责 |
| --- | --- |
| `backend/app/main.py` | FastAPI 路由：建 run、查询、SSE、取消、续跑、故障注入、健康检查 |
| `backend/app/llm.py` | OpenAI 兼容客户端：并发信号量、重试分类、熔断、fallback、费用记账、故障注入 |
| `backend/app/tool_loop.py` | 模型 ↔ 工具循环：工具分发、并行 fan-out、无效调用保护、预算门 |
| `backend/app/orchestrator.py` | supervisor 与 worker 执行器：spawn/read/finish/skip_review、预算账本、评审门、修订上限 |
| `backend/app/budget.py` | token 预算账本：reserve / charge / release |
| `backend/app/artifacts.py` | artifact 前缀校验、slot 元数据、verdict 解析 |
| `backend/app/store.py` | run 内存存储、事件 fan-out、落盘节流 |
| `backend/app/checkpoint.py` | 原子 checkpoint、崩溃恢复、保留上限 |
| `backend/app/events.py` | tick 演示流 + run SSE（snapshot + Last-Event-ID 补发 + 实时尾随） |
| `frontend/src/` | React 仪表盘；EventSource 流 + 2s 轮询兜底 |

## 3. 一次 run 的生命周期

1. `POST /api/runs` 创建 `RunState`，`_launch` 起异步任务执行 `execute_run`。
2. supervisor 用 `spawn_agent(role, task, context)` 派活。并行工具调用通过 `asyncio.gather` fan-out；每个 spawn 在派发前先 `reserve` 预算。supervisor 提供的 context 超过 `CONTEXT_MAX_CHARS` 时截断并附加 `[TRUNCATED]` 标记；worker 只能看到自己的 system prompt、任务与这段 context，看不到 supervisor 会话或兄弟 agent。
3. worker 在自己的工具循环里 `write_artifact` / `read_artifact` / `finish(summary)`；完成后结算预算（退还未用部分）。
4. supervisor 视需要 `read_artifact` 读回内容，或请求修订；`finish(final_answer)` 收尾。
5. 校验：最终答案 ≥20 字符；**至少一次 reviewer verdict 或显式 `skip_review(reason)`**，否则第一次 finish 返回 `review_not_completed` 并记录 `finish_blocked`，第二次放行并标 `unverified=true`。
6. 结束状态：`done` / `budget_exhausted` / `cancelled` / `interrupted` / `failed`；每个终态都写 `run_finished` 事件并强制落盘。

### 评审与修订

- reviewer 写 `reviewer.verdict`，首行必须是 `PASS` 或 `REJECT`；写入即触发 `review_passed` / `review_rejected` 事件，并写入 `run.debug.review_verdict`。
- 每出现一次 `review_rejected`，只允许再派发一次 writer/marketing 修订；超出返回 `revision_cap` 并记 `limit_reached`。
- 任务缺 slot（writer / marketing / reviewer）或 verdict=REJECT 时，run 仍可 `done`，但 `unverified=true`。

## 4. 预算账本

不变量（consumed ≤ budget 时任意时刻成立）：

```
tokens_used + reserved_tokens + remaining == budget_tokens
```

- spawn 时 `reserve = min(3000, remaining)`，拿不到返回 `budget_unavailable`（若已耗尽则 `budget_exhausted`）。
- 每一步用量的 `charge` 先扣自己预留桶，超出部分直接计入 consumed。
- `release` 退还未用预留；`refunded` 写在 `budget_settled` 事件里。
- 90% 软限只发一次 `budget_soft_limit` 事件；100% 硬停置 `budget_hard_stop`。
- 并发会带来有界超支：每个活跃 agent 最多再跑完当前一步。实测 10k 预算、4 个 agent 冲到 13,160。

## 5. 错误分类与容错

| kind | 触发 | 处理 |
| --- | --- | --- |
| `retryable` | 429 / 5xx / 超时 | 指数退避重试；可切 fallback |
| `connect` | 传输层失败 | 重试；可切 fallback |
| `quota` | 402 / 余额不足关键字 | 不重试；可切 fallback |
| `auth` | 401 / 403 | 不重试；可切 fallback |
| `task_400` | 400 且 body 无结构性关键字 | **收窄重试一次**：去掉 reasoning_content、强制关闭 thinking |
| `structural_400` | 400 且命中 messages/tools/reasoning 等关键字 | 不重试，agent 标 `config_error` |
| `breaker_open` | 同一 base_url 连续失败达阈值 | 冷却后半开试探 |

- 熔断按 base_url 隔离，阈値默认 3 次、冷却 30s。
- 停顿看门狗：180s 无新事件则取消 run，状态 `interrupted`。
- 取消：`cancel_event` + 取消 asyncio 任务；终态 `cancelled`，并置 `tokens_may_be_underreported=true`（在途调用的用量无法记账）。

## 6. 断点续跑

- 每次关键事件强制落盘，其余变更 2s 节流；写盘为 tmp + `os.replace` 原子替换。
- 进程重启加载 checkpoint；`queued/running` 的 run 标为 `interrupted`，清空预留，running 节点改 `cancelled`。
- `POST /api/runs/{id}/resume` 要求额外预算且可用余量 ≥1000 tokens；重置预留、硬停、最终答案与 `unverified`。
- 新 supervisor 收到 resume brief（已完成 agent 摘要 + 缺失 slot）；重复派发同 role+task 直接返回缓存结论（`duplicate_task`），不重复调用模型。
- 实测：10k 预算跑爆 → 重启从盘恢复 → +40k 续跑 → done，43.8k tokens，未重跑已完成 writer/marketing。

## 7. 事件流

- `GET /api/runs/{id}/stream`：`: connected` → `snapshot`（当前完整状态）→ 补发 `Last-Event-ID` 之后的事件 → 实时尾随（10s 心跳 `: ping`）→ 终态补发最终 snapshot 后关闭。
- 客户端按下发 `id` 去重；前端 EventSource 断线自动重连并从 `lastId` 续传，页面另有 2s 轮询兜底刷新树/预算。
- 前端只在流终态后停止重连，不在首个终态 snapshot 处主动关闭，避免丢掉补发转录。

## 8. 前端

- 侧栏：新建 run（任务/预算/深度/并发）、run 列表、故障注入、tick 演示。
- 主区：状态头（含取消/续跑/重连）、预算条、debug 字段、agent 树 + 选中详情、artifact 表（含 last writer）、最终答案（unverified 等标记）、可过滤事件转录。
- 点击树节点打开该 agent 的 Conversation 面板：完整 system prompt、任务与 supervisor 提供的 context、每轮 assistant 文本/推理/tool_calls，以及 tool 结果；运行中的 agent 每 1.5s 刷新。转录随 checkpoint 落盘，重启后仍可查看。
- 无 UI 框架，内联样式，`tsc --noEmit` 作为类型门。

## 9. 关键取舍

- **工具循环不用流式**：一次性返回 tool_calls，便于记账与重放；代价是首 token 延迟不作为优化目标。
- **supervisor 等待 spawn 完成**：并行 fan-out 用 gather，但 supervisor 本身不并发继续规划；足够演示且状态机简单。
- **artifact 存内存 + checkpoint**：内容不进入公开 API（slot 只给元数据），避免草稿意外泄漏到列表接口。
- **required slots 固定三角色**：任务只需 writer 时也会因缺 marketing 标 unverified；这是“缺什么标什么”的保守策略，最终答案不受影响。
- **resume 不复用 partial**：partial 可能停在半个工具往返，复用会把“未完成”当结论；只复用 done。

## 10. 测试

`backend/tests` 全部离线（假模型），41 条覆盖：预算账本不变量、软/硬限、深度工具表、去重、取消与少记标记、12 agent 上限、上下文隔离（含每个 agent 的转录内容、超长 context 的 `[TRUNCATED]` 标记与 checkpoint 往返）、token 对账、预留耗尽 → partial、越权写入、评审门/skip_review、未知工具、结构 400、任务 400 收窄重试、可重试重试次数、reasoning 回传、SSE 补发/实时/去重、checkpoint 往返与 resume 复用。

真实模型的验证只通过少量探针和小 run 完成，原始记录在 `ai-logs/`。