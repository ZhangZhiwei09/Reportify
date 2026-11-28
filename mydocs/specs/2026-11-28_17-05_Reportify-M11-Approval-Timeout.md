# Reportify M11 · Approval Timeout — Spec

> 层级：Feature Spec（§12+ 功能按契约先行）
> 依据：`02-agent-runtime.md` §11（审批无人处理）、`05-conversation-task.md` §6.1/§9、`07-api-and-ui.md` §5.1。
> 前置：M0–M10 已实现（375 项测试通过）。挂起的审批目前只能由人决策，否则 `waiting_approval` 永久保留。

---

## 0. 状态

| 字段 | 值 |
| --- | --- |
| Phase | `Review` |
| Status | `IMPLEMENTED`（等待用户验收） |
| Approval | 用户指令「按顺序发展把」（2026-11-28），§12+ 第 4 项（OAuth 2.1 前的收尾项） |
| 任务单元 | 审批超时计时、自动拒绝并续跑同一 run、系统消息与审计 |
| 不包含 | 审批超时后取消 run、通知渠道、跨进程持久化计时器 |

**Done Contract**：挂起的审批在 `approval_timeout_seconds` 后自动拒绝，同一 run 继续执行（工具未执行、
审计 `rejected/approval_rejected`、会话留「审批超时」记录）；人为决策后计时器停止。

---

## 1. 目标与验收

1. `approval_timeout_seconds`（默认 900，0 关闭）控制停泊时长。
2. 到期后把仍为 `pending` 的待批项全部置为 `denied`，并以 `DeferredToolResults` 续跑**同一个 run**。
3. 被拒绝的工具不执行（Fake MCP 无调用），`tool_call_audit` 记 `rejected` + `approval_rejected`。
4. 会话中追加 `system_event` 消息「审批超时（Ns），已自动拒绝：…」，payload 含 `code=approval_timeout`。
5. 人为决策（批准/拒绝）完成后计时器取消；`cancel`、`shutdown` 也清理计时器，不泄漏任务。
6. 到期时 run 已不是 `waiting_approval`（已决策/已取消）则什么也不做。
7. `/config` 暴露 `approvals.timeout_seconds`。
8. `ruff`、`pytest` 全绿（含既有 375 项）。

---

## 2. In / Out of Scope

**In**：`AgentRuntime` 计时器、配置项、`/config` 字段、集成测试、文档回写。

**Out**：超时后直接取消、审批提醒通知、计时器持久化（重启后由 `recover_stale_runs` 兜底）。

---

## 3. Research Findings

| 事实 | 结论 | 影响 |
| --- | --- | --- |
| 停泊状态全在进程内（`history_blob` + `pending_approvals`） | 计时器只能是进程内 task | 重启后由启动恢复兜底 |
| `decide()` 已完成「全部决策后同 run 续跑」 | 超时可直接复用 `decide` | 不新增续跑路径 |
| 续跑时 `clear_pending_approvals` 清空待批项 | 不能靠 API 事后看决策 | 证据改用审计 + 消息 |
| `run_event` 类型是封闭集合 | 不新增事件类型 | 用系统消息 + 审计表达 |

---

## 4. Open Questions（默认决策）

| # | 问题 | 决策 |
| --- | --- | --- |
| Q1 | 超时语义 | 自动**拒绝**并续跑，而非取消：让 Agent 有机会说明「写入被拒绝」 |
| Q2 | 计时起点 | 停泊时刻（`mark_waiting_approval` 之后） |
| Q3 | 部分决策后超时 | 仍拒绝剩余 `pending` 项，然后续跑 |
| Q4 | 关闭方式 | `approval_timeout_seconds=0` |
| Q5 | 重启 | 内存计时器丢失，由 `recover_stale_runs` 将超期 `waiting_approval` 标记 `failed` |

---

## 5. Plan（Contract）

### 5.1 File Changes

| 路径 | 动作 | 内容 |
| --- | --- | --- |
| `src/reportify/modules/runtime/runtime.py` | 更新 | `_approval_timers`、`_start/_cancel_approval_timer`、`_expire_approvals`、`_deny_expired`；`decide`/`cancel`/`shutdown` 清理 |
| `src/reportify/core/config.py` | 更新 | `approval_timeout_seconds: int = 900` |
| `src/reportify/api/routes/system.py` | 更新 | `approvals.timeout_seconds` |
| `.env.example` | 更新 | `REPORTIFY_APPROVAL_TIMEOUT_SECONDS` |
| `tests/integration/test_approval_timeout.py` | 新增 | 停泊 → 超时 → 拒绝 → 续跑成功 |
| `docs/architecture/02,05,09` | 更新 | 失败模式、实现注记、进度 |

### 5.2 关键签名

```python
def _start_approval_timer(self, run_id: UUID) -> None: ...
def _cancel_approval_timer(self, run_id: UUID) -> None: ...
async def _expire_approvals(self, run_id: UUID, seconds: float) -> None: ...
async def _deny_expired(self, run_id: UUID) -> None: ...
```

### 5.3 行为细节

- `_start_approval_timer` 在 `_defer_for_approval` 末尾调用；`seconds <= 0` 直接返回。
- `_expire_approvals` sleep 后调用 `_deny_expired`；`CancelledError` 静默返回，其他异常只记日志。
- `_deny_expired` 重新读取 run：非 `waiting_approval` 或已无 pending 则返回；逐条 `decide(..., approved=False)`，
  `Conflict/NotFound` 视为已被他人处理。
- `_cancel_approval_timer` 不取消「当前正在执行的计时器任务」（超时路径会通过 `decide` 间接触发取消）。
- `shutdown()` 先取消全部计时器，再取消 run 任务。

### 5.4 Checklist

- [x] 1. 计时器与配置。
- [x] 2. 自动拒绝并续跑。
- [x] 3. 系统消息与审计证据。
- [x] 4. 集成测试与全量回归。
- [x] 5. Reverse Sync：02/05/09 与 Spec。

---

## 6. 验证方式

| 项 | 命令 / 操作 | 期望 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | 通过 |
| 集成 | `pytest tests/integration/test_approval_timeout.py` | 停泊 → 1s 后自动拒绝 → run `succeeded` |
| 审计 | 查询 `tool_call_audit` | `rejected` / `approval_rejected` |
| 工具未执行 | Fake MCP `calls` | 空 |
| 全量 | `uv run pytest -q` | 全绿 |

---

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 计时器误杀人工决策 | 只在状态仍为 `waiting_approval` 时动作；`decide` 幂等容错 |
| 计时器泄漏 | `decide`/`cancel`/`shutdown` 统一清理；当前任务不自取消 |
| 重启后仍挂起 | 既有 `recover_stale_runs` 兜底为 `failed` |
| 超时过于激进 | 默认 900s，可配置，可关闭 |

---

## 8. Execute Log

| # | 动作 | 结果 |
| --- | --- | --- |
| 1 | 计时器 | `_approval_timers` + start/cancel/expire；`current_task()` 自取消保护 |
| 2 | 拒绝并续跑 | `_deny_expired` 逐条 `decide(approved=False)`，末条触发同 run 续跑 |
| 3 | 审计/消息 | 续跑产生 `rejected/approval_rejected` 审计；会话追加「审批超时」系统消息 |
| 4 | 配置 | `approval_timeout_seconds`（默认 900，0 关闭）；`/config.approvals.timeout_seconds` |
| 5 | 测试 | 1 个集成测试覆盖停泊→超时→拒绝→成功；全量 376 passed |

## 9. Verification Evidence

| 项 | 命令 / 操作 | 结果 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | `All checks passed!` |
| 全量测试 | `REPORTIFY_TEST_DATABASE_URL=… uv run pytest -q` | `376 passed, 1 skipped in 124.20s` |
| 超时集成 | `pytest tests/integration/test_approval_timeout.py` | 1 passed |
| 状态流转 | 测试内轮询 | `waiting_approval` → （1s）→ `succeeded`，`error=null` |
| 工具未执行 | `fake_mcp.calls` | `[]` |
| 审计 | `tool_call_audit` | `rejected` / `approval_rejected` |
| 用户可见 | 会话消息 | 含「审批超时（1s），已自动拒绝」 |

## 10. Plan-Execution Diff

| 项 | 计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| 决策可观测 | 计划读 `pending_approvals` | 改用审计 + 系统消息 | 续跑会清空 `pending_approvals`（`clear_pending_approvals`） |
| 事件 | 计划可能新增事件 | 不新增 | `run_event.event_type` 是封闭集合，改用系统消息 |
| 计时器启动点 | 计划停泊后 | 同（`_defer_for_approval` 末尾） | 一处覆盖所有停泊路径 |

## 11. Review Verdict

| 轴 | 检查项 | 结论 | 证据 |
| --- | --- | --- | --- |
| Axis-1 | 目标与验收明确 | PASS | §1（8 条） |
| Axis-1 | 逐条验证 | PASS | §9（7 项证据） |
| Axis-2 | Checklist 完成 | PASS | §5.4 |
| Axis-2 | 偏差记录 | PASS | §10（3 项） |
| Axis-3 | 安全 | PASS | 超时只做拒绝，绝不自动批准；工具未执行 |
| Axis-3 | 正确性 | PASS | 376 项测试；真实 Fake MCP 端到端 |
| Axis-3 | 可维护性 | PASS | 复用 `decide`，无第二条续跑路径 |
| Axis-3 | 未覆盖项 | PARTIAL | 计时器不持久化（重启由 stale 恢复兜底）；无通知 |

**Overall Verdict：PASS（附后续项）**。审批不再可能永久挂起。

## 12. Gate

- 当前 `Review`，等待用户验收。
- 剩余 §12+：OAuth 2.1（MCP 授权码 + PKCE），需要单独 Spec 与外部授权服务器验证。
