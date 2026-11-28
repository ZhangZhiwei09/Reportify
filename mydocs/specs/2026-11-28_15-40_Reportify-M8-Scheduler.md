# Reportify M8 · Scheduler — Spec

> 层级：Feature Spec（实现阶段，§12+ 功能按契约先行）
> 依据：`docs/architecture/01-system-overview.md` §5（ARQ 边界）、`05-conversation-task.md` §6.3（`trigger='scheduled'` 与 `idempotency_key`）、
> `07-api-and-ui.md` §5（Run 幂等）与 §6（定时任务视图）、`08-data-model.md` §5（`task_run.trigger`）、`09-engineering.md` §10。
> 前置：M0–M7 已实现（318 项测试通过）。`scheduler.html` 与 `/config features.scheduler=false` 为占位。

---

## 0. 状态

| 字段 | 值 |
| --- | --- |
| Phase | `Review` |
| Status | `IMPLEMENTED`（等待用户验收） |
| Approval | 用户指令「按顺序发展把」（2026-11-28），按 §12+ 顺序推进 |
| 任务单元 | 定时任务：Cron 解析、`schedule` 表与迁移、tick 认领与派发、`/schedules` API、无人工干预运行语义、管理台视图 |
| 不包含 | 水平扩展的 ARQ worker、任务依赖 DAG、Cron 秒级字段、按会话而非任务的调度、邮件/Webhook 通知 |
**Done Contract**：一条启用的 `schedule` 在每个 Cron 时刻产生且仅产生一个 `task_run`（`trigger='scheduled'`、`schedule_id`、`idempotency_key`）；
无人值守运行不会挂起等审批；重复 tick 与重复 HTTP 重试不产生重复 Run；`ruff` 与 `pytest` 全绿。

---

## 1. 目标与验收

1. `POST /api/v1/schedules` 以 `{task_id, cron, timezone?, name?, enabled?}` 创建定时任务；非法 Cron 返回 `400 invalid_argument`，未知任务返回 `404`。
2. `GET/PATCH/DELETE /api/v1/schedules[/{id}]` 支持列表、改期、启停、删除；改 `cron`/`timezone` 后 `next_run_at` 立即重算。
3. tick 认领到期任务：`UPDATE`/`FOR UPDATE SKIP LOCKED` 保证同一 `schedule` 在一次 tick 只被一个进程认领；多进程部署下不会重复派发。
4. 派发前先把 `next_run_at` 推进到 `now` 之后的第一个时刻，因此派发失败（`conversation_busy`、模型未配置）不会造成死循环重试。
5. 每个派生的 `task_run` 带 `schedule_id`、`trigger='scheduled'`、`idempotency_key='schedule:<id>:<scheduled_for ISO>'`；唯一索引保证重复键不会插入第二行。
6. 无人值守运行不向模型暴露需审批的工具（第 1 层过滤），`plan` 事件标注 `unattended=true` 并列出被隐藏的工具；因此定时运行不会进入 `waiting_approval`。
7. `POST /api/v1/schedules/{id}/run` 立即派发一次（`trigger='api'`），返回 `202` + `run_id`；会话忙时返回 `409 conversation_busy`，并在 `schedule.last_status` 记录 `skipped`。
8. `POST /api/v1/tasks/{id}/runs` 支持 `Idempotency-Key` 头（`07 §5` 已承诺的幂等语义）：同键重试返回同一 Run，不新增行。
9. `/scheduler` 页面显示定时任务列表、Cron、启停、上次/下次执行与最近 Run，不再出现「未启用（§12+）」。
10. `ruff`、`pytest` 全绿（含既有 318 项）。

---

## 2. In / Out of Scope

**In**：`db/models/schedule.py`、`0007_scheduler` 迁移、`schedule` 仓储、`modules/scheduler/{cron,schemas,service}.py`、
`/api/v1/schedules` 路由、`AgentRuntime.start` 的幂等与无人值守过滤、`/config` 能力位、`scheduler.html` + `views/scheduler.js`、
单元/集成测试、架构文档回写。

**Out**：ARQ worker 与 Redis 队列、Cron 秒级/年字段与 `@daily` 别名、错过窗口补跑（catch-up > 1）、通知渠道、任务依赖。

---

## 3. Research Findings

| 事实 | 结论 | 影响 |
| --- | --- | --- |
| `task_run.trigger` 已支持 `scheduled`，预算按 2× 额度执行（`runtime._budget`） | 运行时无需为定时运行改额度 | 只补 `schedule_id` / `idempotency_key` |
| `RunRequest` 已有 `idempotency_key` 字段但从未落库 | 幂等只差一列 + 唯一索引 | 迁移 0007 增加两列 |
| `07 §5` 声明「创建 Run 支持 `Idempotency-Key`」 | 现状未实现 | 本里程碑补齐 |
| 审批路径依赖人在场（`waiting_approval` 停泊） | 定时运行必须避免停泊 | 第 1 层过滤需审批工具 |
| `settings.redis_url` 可选、测试无 Redis | 队列不可作为硬依赖 | 进程内 tick + DB 行锁 |
| `TestClient` 暴露 `portal` | 同步测试可驱动异步 tick | 无需另建事件循环 |

---

## 4. Open Questions（默认决策）

| # | 问题 | 决策 |
| --- | --- | --- |
| Q1 | 调度载体 | **进程内 asyncio tick + `FOR UPDATE SKIP LOCKED` 认领**；不引入 ARQ/Redis。多实例下 DB 行锁保证不重复；单实例下零额外依赖 |
| Q2 | Cron 语法 | 5 字段（分 时 日 月 周），支持 `*`、`n`、`a-b`、`*/n`、`a-b/n`、逗号列表；周 0/7 = 周日（Vixie 语义）；`日` 与 `周` 同时受限时取 **OR** |
| Q3 | 时区与 DST | `zoneinfo`；按墙钟计算，不存在的本地时刻落到偏移后的真实时刻，重复时刻取 `fold=0`（第一次） |
| Q4 | 错过窗口 | 默认 **skip**：`next_run_at` 直接推进到当前之后；不补跑历史窗口 |
| Q5 | 无人值守与审批 | 定时运行隐藏需审批工具；`generate_report`（write 但已全局授予）不受影响 |
| Q6 | 手动「立即运行」 | `trigger='api'`，允许对已暂停的 schedule 手动运行（显式用户动作） |
| Q7 | 删除任务 | 删除 `schedule` 不删历史 Run（`task_run.schedule_id` 置空），保留可追溯性 |
| Q8 | 时区默认 | `UTC`；API 接受 IANA 名称，非法时区返回 `400` |

---

## 5. Plan（Contract）

### 5.1 File Changes

| 路径 | 动作 | 内容 |
| --- | --- | --- |
| `src/reportify/db/migrations/versions/0007_scheduler.py` | 新增 | `schedule` 表、`task_run.schedule_id` / `idempotency_key`、索引与唯一约束 |
| `src/reportify/db/models/schedule.py` | 新增 | `Schedule` 实体（与 08 §5 命名一致） |
| `src/reportify/db/models/task.py` | 更新 | `TaskRun.schedule_id`、`TaskRun.idempotency_key` |
| `src/reportify/db/repositories/schedules.py` | 新增 | CRUD + `claim_due()`（`SKIP LOCKED`）+ `record_dispatch()` |
| `src/reportify/db/repositories/tasks.py` | 更新 | `create_run(schedule_id=, idempotency_key=)`；`run_by_idempotency_key()` |
| `src/reportify/modules/scheduler/cron.py` | 新增 | `CronExpression.parse/matches/next_after`，纯函数 |
| `src/reportify/modules/scheduler/schemas.py` | 新增 | `ScheduleCreate/Update/Read`、`ScheduleRunRead` |
| `src/reportify/modules/scheduler/service.py` | 新增 | `SchedulerService.create/update/delete/list/get/run_now/tick/start/stop` |
| `src/reportify/modules/runtime/schemas.py` | 更新 | `RunRequest.schedule_id` |
| `src/reportify/modules/runtime/runtime.py` | 更新 | 幂等预检、无人值守工具过滤、`plan` 事件 `unattended` |
| `src/reportify/api/routes/schedules.py` | 新增 | `/schedules` 六个端点 |
| `src/reportify/api/routes/tasks.py` | 更新 | `Idempotency-Key` 头 |
| `src/reportify/api/app.py` / `deps.py` | 更新 | 装配 `SchedulerService`，lifespan 启停，依赖注入 |
| `src/reportify/core/config.py` | 更新 | `scheduler_enabled`、`scheduler_tick_seconds`、`scheduler_batch_size` |
| `src/reportify/api/routes/system.py` | 更新 | `features.scheduler=true` |
| `src/reportify/templates/scheduler.html` | 重写 | 列表 + 新建表单 + 启停/立即运行/删除 |
| `src/reportify/static/views/scheduler.js` | 重写 | 调用 `/schedules` API，`textContent` 渲染 |
| `tests/unit/test_cron.py` | 新增 | 语法、边界、时区、OR 语义、非法表达式 |
| `tests/integration/test_schedules_api.py` | 新增 | CRUD、立即运行、幂等头、忙时跳过 |
| `tests/integration/test_scheduler_tick.py` | 新增 | tick 派发/去重/暂停/忙时记录（fake runtime） |
| `tests/integration/conftest.py` | 更新 | TRUNCATE 加入 `schedule` |
| `tests/integration/test_workspace_api.py` | 更新 | `features.scheduler` 断言改为 `True` |

### 5.2 关键签名

```python
class CronExpression:
    @classmethod
    def parse(cls, expression: str) -> "CronExpression": ...
    def matches(self, local: datetime) -> bool: ...
    def next_after(self, after: datetime, tz: ZoneInfo) -> datetime: ...   # -> aware UTC

class SchedulerService:
    async def create(self, payload: ScheduleCreate) -> Schedule: ...
    async def update(self, schedule_id: UUID, payload: ScheduleUpdate) -> Schedule: ...
    async def delete(self, schedule_id: UUID) -> None: ...
    async def list(self, *, limit: int, offset: int) -> list[ScheduleRead]: ...
    async def get(self, schedule_id: UUID) -> ScheduleRead: ...
    async def run_now(self, schedule_id: UUID) -> UUID: ...
    async def tick(self, *, now: datetime | None = None) -> list[UUID]: ...
    async def start(self) -> None: ...   # 仅 scheduler_enabled 时启动循环
    async def stop(self) -> None: ...

async def claim_due(session, *, now: datetime, limit: int) -> list[ScheduleClaim]: ...
```

### 5.3 行为细节

- **表结构**（08 §5 增量）：

  | 字段 | 类型 | 约束 | 说明 |
  | --- | --- | --- | --- |
  | `id` | UUID | PK | |
  | `task_id` | UUID | FK `analysis_task` CASCADE | 被重复执行的任务 |
  | `conversation_id` | UUID | FK `conversation` CASCADE | 冗余，用于列表与锁 |
  | `name` | text | NOT NULL | 默认取 task.goal 前 40 字 |
  | `cron` | text(120) | NOT NULL | 5 字段表达式 |
  | `timezone` | text(64) | NOT NULL, 默认 `UTC` | IANA 名称 |
  | `enabled` | bool | NOT NULL, 默认 true | |
  | `next_run_at` | timestamptz | NOT NULL | 始终为未来最近一次 |
  | `last_run_at` | timestamptz | NULL | 最近一次派发对应的计划时刻 |
  | `last_run_id` | UUID | FK `task_run` SET NULL | |
  | `last_status` | text | CHECK `dispatched/skipped/failed` | |
  | `last_error` | jsonb | NULL | `{code, detail}` |

  约束：`UNIQUE (task_id, cron, timezone)`、`INDEX (enabled, next_run_at)`；
  `task_run` 增量：`schedule_id`（FK `schedule` SET NULL）、`idempotency_key`（text NULL，**唯一部分索引**）。

- **tick 流程**：`SELECT … WHERE enabled AND next_run_at <= now ORDER BY next_run_at LIMIT n FOR UPDATE SKIP LOCKED`
  → 逐行把 `next_run_at` 推进到 `now` 之后（解析失败则 `enabled=false` + `last_status='failed'`）→ 提交
  → 事务外派发，写回 `last_run_at/last_run_id/last_status/last_error`。
- **幂等键**：定时 `schedule:{schedule_id}:{scheduled_for.isoformat()}`；手动 `schedule:{schedule_id}:manual:{now.isoformat()}`。
- **无人值守**：`specs = [s for s in specs if not s.requires_approval]`（同时过滤 `risk_level=='destructive'`），
  `plan` 事件追加 `unattended=true` 与 `hidden_tools`；`warnings` 追加说明。
- **时区校验**：`ZoneInfo(name)` 失败 → `InvalidArgument`；`next_after` 失败（永不触发）→ `InvalidArgument`。
- **run_now**：`latest user message` 缺失 → `409 conflict`（`schedule has no user message to run`）；会话忙 → `ConversationBusy` 原样上抛，并记录 `skipped`。

### 5.4 Checklist

- [x] 1. 迁移 0007 + 模型 + 仓储（含 `SKIP LOCKED`）。
- [x] 2. Cron 解析与纯函数测试。
- [x] 3. `SchedulerService` + 运行时幂等/无人值守改造。
- [x] 4. `/schedules` API + `Idempotency-Key` 头 + `/config`。
- [x] 5. 管理台视图与测试更新。
- [x] 6. 全量回归（M0–M7 不回归）。
- [x] 7. Reverse Sync：01/02/05/07/08/09 与 Spec。

---

## 6. 验证方式

| 项 | 命令 / 操作 | 期望 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | 通过 |
| Cron 单测 | `pytest tests/unit/test_cron.py` | 语法/边界/时区/OR 全通过 |
| 调度单测 | `pytest tests/integration/test_scheduler_tick.py` | 派发一次、重复 tick 不重复、暂停不派发、忙时 `skipped` |
| API | `pytest tests/integration/test_schedules_api.py` | CRUD、立即运行、`Idempotency-Key` 幂等 |
| 无人值守 | 定时运行 `plan` 事件 | `unattended=true`，需审批工具不在 `tools` 中，运行不进入 `waiting_approval` |
| 页面 | `GET /scheduler` | 列表容器存在，无「未启用（§12+）」 |
| 全量 | `uv run pytest -q` | 全绿 |

---

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 多实例重复派发 | `FOR UPDATE SKIP LOCKED` + `idempotency_key` 唯一索引双保险 |
| 自研 Cron 与标准实现偏差 | 5 字段受限于数字语法；用表驱动测试固定边界；不支持别名即报错 |
| DST 边界 | 墙钟语义 + `fold=0`，在 `docs` 中声明；测试只断言单调与 UTC 转换 |
| 无人值守静默丢能力 | `plan` 事件与 `warnings` 明示被隐藏的工具，报告可追溯 |
| 调度循环拖垮 API | 单次 tick 限量 `scheduler_batch_size`，异常只记日志不退出循环 |
| 停止服务时丢失窗口 | `next_run_at` 已在派发前推进；重启后 skip 历史窗口（Q4） |

---

## 8. Execute Log

| # | 动作 | 结果 |
| --- | --- | --- |
| 1 | 迁移 | `0007_scheduler`：`schedule` 表、`task_run.schedule_id` / `idempotency_key`、唯一部分索引、`(enabled, next_run_at)` 索引；降级/升级往返验证通过 |
| 2 | 模型 | `db/models/schedule.py` 新增 `Schedule`；`TaskRun` 增加两列与索引 |
| 3 | 仓储 | `db/repositories/schedules.py`：CRUD、`lock_due`（`SKIP LOCKED`）、`record_dispatch`、`run_counts`、`recent_runs` |
| 4 | Cron | `modules/scheduler/cron.py`：5 字段解析、`matches`、`next_after`（zoneinfo、DST、dom/dow OR） |
| 5 | 服务 | `modules/scheduler/service.py`：CRUD、`run_now`、`tick`、`start/stop`、幂等键与状态回写 |
| 6 | 运行时 | `RunRequest.schedule_id`；`start` 幂等预检；无人值守工具过滤 `hide_approval_gated`；`plan` 事件 `unattended` / `hidden_tools` |
| 7 | API | `/api/v1/schedules` 六个端点；`POST /tasks/{id}/runs` 支持 `Idempotency-Key`；`/config` 增 `features.scheduler` 与 `scheduler.loop_enabled` |
| 8 | 视图 | `scheduler.html` 与 `views/scheduler.js`：列表、新建、启停、立即运行、删除 |
| 9 | 测试 | 新增 28 个单元 + 12 个集成测试；全量 358 passed / 1 skipped |
| 10 | 回写 | 本 Spec、01 §4/§5/§8、02 §2/§7.2、05 §6.3/§9、07 §5.1.1/§7.1/§10、08 §6.9/§6.20、09 §5/§6/§11 |

## 9. Verification Evidence

| 项 | 命令 / 操作 | 结果 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | `All checks passed!` |
| 全量测试 | `REPORTIFY_TEST_DATABASE_URL=… uv run pytest -q` | `358 passed, 1 skipped in 120.30s` |
| Cron 单测 | `pytest tests/unit/test_cron.py` | 25 passed（语法、边界、周日 0/7、时区、OR、DST、永不触发） |
| 无人值守过滤 | `pytest tests/unit/test_runtime_guards.py` | 2 passed（隐藏需审批/破坏性工具，无需隐藏时返回原列表） || tick 语义 | `pytest tests/integration/test_scheduler_tick.py` | 5 passed：派发一次并推进 `next_run_at`、重复 tick 不重复、暂停不派发、忙时 `skipped`、永不触发则禁用 |
| API | `pytest tests/integration/test_schedules_api.py` | 6 passed：CRUD、非法 Cron/时区/任务、重复 409、立即运行、忙时 409、`Idempotency-Key` 同键同 Run |
| 真实循环 | `pytest tests/integration/test_scheduler_loop.py` | 1 passed：1s tick 自动派发，`plan.unattended=true`、`hidden_tools=["fake_write"]`、Run `succeeded` |
| 迁移往返 | `alembic downgrade 0006` → `alembic upgrade head` | 两向均成功；`alembic current` = `0007 (head)` |
| 幂等落库 | 集成测试查询 `task_run` | 同键仅 1 行；`schedule:<id>:manual:<ts>` 前缀符合约定 |

## 10. Plan-Execution Diff

| 项 | 计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| 调度载体 | 架构 01 D-01 写「ARQ 跑定时任务」 | API 进程内 asyncio tick，DB 行锁认领；ARQ 仅保留预留 | 测试环境无 Redis；`SKIP LOCKED` 已提供跨进程互斥，避免为一个功能引入两套部署依赖 |
| tick 认领接口 | 计划 `claim_due()` 在仓储内推进 | `lock_due()` 只锁行，推进与提交在 `SchedulerService` | Cron 语义留在 service，仓储保持纯持久化 |
| `/config` | 计划只改 `features.scheduler` | 另加 `scheduler.loop_enabled/tick_seconds` | 开关状态可观测，测试据此断言循环被关闭 |
| tick 测试时钟 | 固定 `NOW=2030` 便于断言 | 增加 autouse fixture 清空 `schedule` | 固定时钟会把其他用例的残留 schedule 视为到期，导致重复派发 |
| 手动运行 trigger | 计划 `api` | 同 | 与 08 `trigger` CHECK 一致 |
| `run_count` | 计划聚合统计 | 通过新增 `task_run.schedule_id` 聚合 | 明确归属，顺带支持 `/schedules/{id}/runs` |

## 11. Review Verdict

| 轴 | 检查项 | 结论 | 证据 |
| --- | --- | --- | --- |
| Axis-1 | 目标与验收标准明确 | PASS | §1（10 条） |
| Axis-1 | 验收项逐条验证 | PASS | §9（10 项证据） |
| Axis-2 | Checklist 1–7 完成 | PASS | §5.4 |
| Axis-2 | 偏差已记录 | PASS | §10（6 项） |
| Axis-3 | 安全 | PASS | 无人值守隐藏需审批工具；Cron 注入面仅文本字段；`/schedules` 走既有 Bearer；无 LLM 生成代码 |
| Axis-3 | 正确性 | PASS | 357 项测试；真实 1s tick 端到端；迁移往返 |
| Axis-3 | 一致性 | PASS | 08 §6.20 与迁移/模型字段逐一对齐；07 §5.1.1 与实际路由一致 |
| Axis-3 | 未覆盖项 | PARTIAL | 无多实例并发压测（仅逻辑依赖 `SKIP LOCKED`）；无通知渠道；Cron 不支持别名与秒级 |

**Overall Verdict：PASS（附后续项）**。定时任务从「占位」变为可用能力，且不引入新的部署依赖。

## 12. Gate

- 当前 `Review`，等待用户验收。
- 后续 §12+：Report Revision（版本树）、Memory、OAuth 2.1、审批超时。
