# Reportify M5 · 契约收尾 — Spec

> 层级：Feature Spec（实现阶段）
> 依据：`docs/architecture/07-api-and-ui.md` §5.1、§5.4、§5.5；`03` §9.2；`05` §6.1、§9；`08` §6.19。
> 前置：M0–M4 已实现（257 项测试通过）。本里程碑只补齐 07 契约中尚未落地的三处，不新增范围。

---

## 0. 状态

| 字段 | 值 |
| --- | --- |
| Phase | `Review` |
| Status | `IMPLEMENTED`（等待用户验收） |
| Approval | 用户指令「推送分支，然后继续完成剩下的任务」（2026-11-22） |
| 任务单元 | ① 写工具审批（`waiting_approval` 恢复）② Workspace API 与 `workspace_audit` 落库 ③ `GET /config` |
| 不包含 | 审批超时自动取消（24h 策略）、ARQ、报告正式渲染器、§12+ 任何模块 |

**Done Contract**：`DeferredToolRequests` 能落库、经 API 批准/拒绝后**同 run 续跑**；
Workspace 文件可列出/读取/重载并写 `workspace_audit`；`/config` 返回非敏感能力；
`ruff` 与 `pytest` 全绿；07 §5 的端点清单闭合。

---

## 1. 目标与验收

1. 需要在执行前审批的工具（MCP `destructive`，或 `tool_definition.requires_approval=true`）：
   run 进入 `waiting_approval`，工具**未执行**，发布 `approval_required` 事件，待审批项落库。
2. `GET /api/v1/runs/{id}/approvals` 返回待审批项（含 `tool_name`、`args_redacted`、`risk`、`decision`）。
3. `POST /api/v1/runs/{id}/approvals/{approval_id}` 接受 `{"decision": "approve"|"deny"}`；
   全部决策完成后同一个 run 续跑：批准则执行工具，拒绝则回灌拒绝结果；run 最终 `succeeded`。
4. 非审批工具的行为完全不变（M2–M4 的 257 项测试继续通过）。
5. `GET /api/v1/workspace/files` 列出 workspace 内文件（路径、大小、sha256）；
   `GET /workspace/files/{path}` 返回 UTF-8 文本（限 128KB、禁止越界）；
   `POST /workspace/reload` 重新扫描并写审计；`GET /workspace/audits` 返回审计记录。
6. `workspace_audit` 在加载时写入：首次 `loaded`、内容变化 `changed`、校验失败 `rejected`。
7. `GET /api/v1/config` 返回版本、环境、模型是否配置、认证是否开启、功能开关与限额，**不含任何密钥**。
8. `ruff`、`pytest` 全绿，新增测试覆盖上述三类。

---

## 2. In / Out of Scope

**In**：`task_run.pending_approvals`（迁移 `0005`）、运行时延期与续跑、审批 API、
`WorkspaceService` 与 4 个 workspace 端点、`/config`、测试。

**Out**：审批超时策略、审批通知、批量审批、`destructive` 的永久授权、ARQ 调度、§12+。

---

## 3. Research Findings

| 事实 | 实测结论 | 影响 |
| --- | --- | --- |
| 延期返回 | `output_type=[str, DeferredToolRequests]` 时，需审批的 run 输出 `DeferredToolRequests`，`approvals` 里是待批 `ToolCallPart` | 用它落库 |
| 续跑 | `agent.run(message_history=result.all_messages(), deferred_tool_results=DeferredToolResults(approvals={tool_call_id: True/False}))` | 同 run 续跑的实现基础 |
| 未批执行 | 首次 run 中工具**未执行**（实测 `executed == []`） | 审批前不会产生副作用 |
| 拒绝 | `approvals={id: False}` 时不执行，模型收到拒绝结果并可继续回答 | 记 `rejected` 审计 |
| 审批谓词 | `toolset.approval_required(lambda ctx, tool_def, args: bool)` 同步判定 | 用预算好的名称集合判断 |
| `workspace_audit` | M0 建表但从未写入 | 本里程碑补写入 |
| 现有 `requires_approval` | `ToolSpec` 已有该字段；`destructive` 风险恒需审批（03 §9.1） | 组合判定 |

---

## 4. Open Questions（默认决策）

| # | 问题 | 决策 |
| --- | --- | --- |
| Q1 | 谁需要审批 | `risk_level == destructive` 或 `requires_approval=true`；`write` 默认不逐次审批（沿用 M2/M3） |
| Q2 | 部分决策时是否继续等 | 是；全部待批项都有决策才续跑，未决项保持 `waiting_approval` |
| Q3 | `approval_id` 用什么 | `ToolCallPart.tool_call_id`（run 内唯一，无需新 ID 空间） |
| Q4 | 续跑用新 run 还是同 run | **同 run**（05 §9），事件序列继续递增 |
| Q5 | 审批超时 | 不实现自动取消；记录为遗留项（05 §11 的 24h 策略留到后续） |
| Q6 | Workspace 文件范围 | workspace 根内、跳过隐藏文件与 `__pycache__`，最多 500 个，单文件 128KB |

---

## 5. Plan（Contract）

### 5.1 File Changes

| 路径 | 动作 | 内容 |
| --- | --- | --- |
| `src/reportify/db/models/task.py` | 更新 | `TaskRun.pending_approvals JSONB NOT NULL DEFAULT '[]'` |
| `src/reportify/db/migrations/versions/0005_approvals.py` | 新增 | 加列 |
| `src/reportify/db/repositories/tasks.py` | 更新 | 读写 `pending_approvals`、`set_waiting_approval` |
| `src/reportify/modules/runtime/schemas.py` | 更新 | `PendingApproval`、`ApprovalDecision` 模型 |
| `src/reportify/modules/runtime/agent_factory.py` | 更新 | `output_type=[str, DeferredToolRequests]` |
| `src/reportify/modules/runtime/runtime.py` | 更新 | 审批集合、`.approval_required()`、延期落库、续跑、拒绝审计 |
| `src/reportify/api/routes/runs.py` | 更新 | `GET /runs/{id}/approvals`、`POST /runs/{id}/approvals/{approval_id}` |
| `src/reportify/modules/workspace/loader.py` | 更新 | `walk_files()`、`read_file()` |
| `src/reportify/modules/workspace/service.py` | 新增 | `WorkspaceService`：列出/读取/重载 + `workspace_audit` 写入 |
| `src/reportify/api/routes/workspace.py` | 新增 | 4 个 workspace 端点 |
| `src/reportify/api/routes/system.py` | 更新 | `GET /config` |
| `src/reportify/api/deps.py` | 更新 | `get_workspace_service` |
| `src/reportify/api/app.py` | 更新 | 构造 workspace service、注册路由 |
| `tests/integration/test_approvals.py` | 新增 | 待批 → 批准/拒绝 → 续跑 |
| `tests/integration/test_workspace_api.py` | 新增 | 列出/读取/越界/重载/审计 |
| `tests/unit/test_config_endpoint.py` | 新增 | `/config` 不含密钥 |

### 5.2 关键签名

```python
class PendingApproval(BaseModel):
    approval_id: str
    tool_call_id: str
    tool_name: str
    args_redacted: dict[str, Any]
    risk: Literal["write", "destructive"]
    decision: Literal["pending", "approved", "denied"] = "pending"
    created_at: datetime

class AgentRuntime:
    async def decide(self, run_id: UUID, approval_id: str, *, approved: bool) -> RunOutcome | None: ...

class WorkspaceService:
    def list_files(self) -> list[WorkspaceFile]: ...
    def read_file(self, path: str) -> str: ...
    async def reload(self) -> ReloadResult: ...
    async def audits(self, limit: int = 100) -> list[AuditView]: ...
```

### 5.3 行为细节

**审批**

- run 开始时算出 `approval_required_names`：`spec.requires_approval or spec.risk_level == "destructive"`；
  给每个 toolset 套 `.approval_required(lambda ctx, td, args: td.name in names)`。
- `AgentRunResultEvent.result.output` 为 `DeferredToolRequests` 时：
  1. 把 `output.approvals` 转成 `PendingApproval`（参数脱敏复用运行时 `_redact`），写入 `task_run.pending_approvals`；
  2. 保存 `history_blob`（续跑所需）；
  3. `task_run.status = waiting_approval`、`analysis_task.status = waiting_approval`；
  4. 发布 `approval_required` 事件（含 `approval_id`、`tool_name`、`risk`、`args_redacted`）；
  5. 释放会话锁（run 不再活跃），但不可启动新 run（`active_run` 包含 waiting_approval）。
- `POST /runs/{id}/approvals/{approval_id}`：
  - 校验 run 状态为 `waiting_approval`、`approval_id` 存在且未决策，否则 404/409；
  - 写入决策；若仍有 `pending` 项 → 返回当前状态，不续跑；
  - 全部决策完成 → `status=running`、读 `history_blob`、用
    `DeferredToolResults(approvals={tool_call_id: bool})` 续跑；事件 `run_started` 不再重复，改为 `usage`/`tool_result`/`run_completed` 继续。
- 拒绝时工具不执行；审计 `rejected`（`error_code=approval_rejected`），模型收到拒绝结果。

**Workspace**

- `walk_files()` 递归遍历根目录，跳过 `.` 开头、`__pycache__`、符号链接；返回相对路径、大小、sha256。
- `read_file(path)` 复用 loader 的越界/大小/二进制校验；路径必须是 workspace 相对路径。
- `reload()`：`loader.load()` → 对每个文件与上次审计的 hash 比较：无记录 `loaded`，hash 变化 `changed`；
  加载警告 → `rejected`（`file_path` 取警告前缀的路径，取不到用 `"<workspace>"`）；返回计数与 warnings。

**`/config`**

- 返回 `{version, app_env, model: {configured, name}, auth_required, features: {mcp, skills, templates, reports, approvals}, limits: {...}}`；
- 只读配置，绝不返回 `secret_key`/`auth_token`/`deepseek_api_key` 的值。

### 5.4 迁移 0005

`ALTER TABLE task_run ADD COLUMN pending_approvals JSONB NOT NULL DEFAULT '[]'::jsonb`；downgrade 删除该列。

### 5.5 Checklist

- [x] 1. `0005` 迁移 + 模型字段；upgrade/downgrade 各跑一次。
- [x] 2. 运行时期审批集合、`.approval_required()`、延期落库与 `approval_required` 事件。
- [x] 3. 审批 API + 同 run 续跑 + 批准/拒绝审计。
- [x] 4. `WorkspaceService` + 4 个端点 + `workspace_audit` 写入。
- [x] 5. `GET /config`。
- [x] 6. 新增测试（审批、workspace、config）并全量回归（M2–M4 不回归）。
- [x] 7. 真实进程验证审批与 workspace 端点。
- [x] 8. Reverse Sync：更新 02/05/07/08/09 文档与 Spec。

---

## 6. 验证方式

| 项 | 命令 / 操作 | 期望 |
| --- | --- | --- |
| 迁移 | `alembic upgrade head` / `downgrade 0004` | `0005` 列存在；可逆 |
| 静态检查 | `uv run ruff check .` | 通过 |
| 全量测试 | `uv run pytest -q` | 全绿（含原有 257 项） |
| 审批挂起 | destructive MCP 工具 + 授权 | run `waiting_approval`；工具未执行；事件含 `approval_required` |
| 批准 | `POST /approvals/{id}` | run 续跑至 `succeeded`；审计 `succeeded` |
| 拒绝 | 同上 `decision=deny` | 工具未执行；审计 `rejected` |
| 部分审批 | 两个待批只批一个 | 仍 `waiting_approval`；全部批完才续跑 |
| Workspace | 列表/读取/重载/审计 | 200；越界 404；审计有 `loaded`/`changed` |
| Config | `GET /api/v1/config` | 200；不含任何密钥值 |

---

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 续跑重复执行工具 | 延期时工具未执行（已实测）；续跑只带决策 |
| 审批期间会话被占用 | `waiting_approval` 计入活跃 run，新消息返回 409 |
| `output_type` 改为联合类型影响既有 run | 非审批 run 仍输出 `str`；回归测试覆盖 |
| workspace 遍历慢/越界 | 跳过隐藏与符号链接、限 500 个文件、复用 loader 校验 |
| 迁移失败 | 只加可空默认列；downgrade 可逆 |

---

## 8. Execute Log

| # | 动作 | 结果 |
| --- | --- | --- |
| 1 | 迁移 | `task_run.pending_approvals` + `0005`；upgrade / downgrade 各跑一次 |
| 2 | 审批挂起 | Agent 改 `output_type=[str, DeferredToolRequests]`；对 `destructive`/`requires_approval` 工具加 `.approval_required()`；延期写入 `pending_approvals` 与 `history_blob`，发 `approval_required`，task/run 均置 `waiting_approval` |
| 3 | 审批续跑 | `GET/POST /runs/{id}/approvals*`；全部决策后同 run 用 `DeferredToolResults` 续跑；拒绝记 `rejected`/`approval_rejected` |
| 4 | Workspace | `walk_files`/`read_file` + `WorkspaceService` + 4 个端点；`workspace_audit` 记录 `loaded`/`changed`/`rejected` |
| 5 | Config | `GET /api/v1/config`，只返回非敏感能力与限额 |
| 6 | 修复 | 授权层原先把 `needs_approval` 当作「隐藏」，导致审批门永不触发；改为「可见但需审批」 |
| 7 | 验证 | `ruff` 通过；`pytest` 273 passed；真实进程验证 config/workspace/approvals |
| 8 | 回写 | 02 §11.1、05 §9、07 §5.1、08 §6.9、09 §12 |

## 9. Verification Evidence

| 项 | 命令 / 操作 | 结果 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | `All checks passed!` |
| 全量测试 | `REPORTIFY_TEST_DATABASE_URL=… uv run pytest -q` | `273 passed, 1 skipped in 81.51s` |
| 迁移 | `alembic upgrade head` | `0005`；`pending_approvals` 列存在 |
| 审批挂起 | destructive MCP 工具 + 授权 | run `waiting_approval`；`fake_mcp.calls == []`；DB 有 `approval_required` 事件；无审计行 |
| 批准 | `POST /approvals/{id}` `{"decision":"approve"}` | 同 run 续跑至 `succeeded`；工具执行一次；task `completed`；待批清空 |
| 拒绝 | `{"decision":"deny"}` | 工具未执行；审计 `rejected` / `approval_rejected`；run 仍 `succeeded` |
| 部分审批 | 两个待批只批一个 | 仍 `waiting_approval`；全部批完才续跑 |
| 非法审批 | 未知 approval_id / 已结束 run | 404 / 409 |
| 忙碌会话 | `waiting_approval` 期间再发消息 | `409 conversation_busy` |
| Workspace | 列表/读取/隐藏文件/穿越 | 200 / 200 / 不列出 / 400-404-422 且不泄漏 |
| 审计 | reload 两次 | 首次 `loaded>0`，第二次全 0；改文件后 `changed>=1` |
| Config | `GET /api/v1/config` | 200；`features.approvals=true`；响应不含任何密钥 |
| 真实进程 | uvicorn | `/config` 200、`/workspace/files` 200、`/workspace/reload` 200、`/workspace/audits` 200、未知 run 审批 404 |

## 10. Plan-Execution Diff

| 项 | 计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| 授权语义 | 未涉及 | 新增 `_exposable()`：`needs_approval` 的工具仍暴露给模型 | 原实现直接隐藏，审批门无法触发（真 bug） |
| 续跑入参 | `message_history=result.all_messages()` | 从 `history_blob` 反序列化（`ModelMessagesTypeAdapter`） | 续跑跨请求，只能从库里恢复 |
| 待批项存储 | 计划用 `pending_approvals` | 同，含 `decision` 字段 | 部分决策需要持久化 |
| 拒绝审计 | 审计 `rejected` | 同，`error_code=approval_rejected` | SDK 把拒绝表达为 `ToolReturnPart` 文本 |
| 审批超时 | Q5 不实现 | 同 | 05 §11 的 24h 策略留到后续 |
| 测试 | 计划 | 新增 7 个审批用例 + 8 个 workspace/config 用例 | — |
| 环境 | — | 测试 `conftest` 设置 `NO_PROXY=127.0.0.1,localhost,::1` | 本机系统代理（Clash 7890）会把本地 MCP 请求代理成 502 |

> 过程记录：本机 Windows 系统代理（`127.0.0.1:7890`）会让 httpx 把发往 `127.0.0.1` 的 MCP 请求也走代理并返回 502；
> 测试通过 `NO_PROXY` 规避。**生产/本地手工使用时，若启用了系统代理，需要把回环地址加入 `NO_PROXY`**，否则本地 MCP Server 会显示连接失败。

## 11. Review Verdict

| 轴 | 检查项 | 结论 | 证据 |
| --- | --- | --- | --- |
| Axis-1 | 目标与验收标准明确 | PASS | §1 |
| Axis-1 | 验收项逐条验证 | PASS | §9（8 条验收对应 14 项证据） |
| Axis-2 | Checklist 1–8 完成 | PASS | §5.5 |
| Axis-2 | 偏差已记录 | PASS | §10（7 项） |
| Axis-3 | 安全 | PASS | 审批前不执行；参数脱敏入事件/库；workspace 路径校验；`/config` 无密钥 |
| Axis-3 | 正确性 | PASS | 273 项测试；真实进程验证 |
| Axis-3 | 可维护性 | PASS | 审批复用 run 生命周期；workspace 以文件为源 |
| Axis-3 | 未覆盖项 | PARTIAL | 无审批超时策略、无浏览器端审批卡片 E2E |

**Overall Verdict：PASS（附后续项）**。07 §5 的端点清单已闭合。

## 12. Gate

- 当前 `Review`，等待用户验收。
- 下一步：联网环境复验 Docker 构建；§12+ 功能（Memory、Report Engine、Scheduler、OAuth、审批超时）另开 Spec。
