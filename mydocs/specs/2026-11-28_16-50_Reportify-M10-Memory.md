# Reportify M10 · Memory — Spec

> 层级：Feature Spec（§12+ 功能按契约先行）
> 依据：`02-agent-runtime.md` §8 step 6（`MemoryProvider` 占位）、`08-data-model.md`、`07-api-and-ui.md` §5。
> 前置：M0–M9 已实现（365 项测试通过）。`MemoryProvider` 仅存在于文档，运行时未接入。

---

## 0. 状态

| 字段 | 值 |
| --- | --- |
| Phase | `Review` |
| Status | `IMPLEMENTED`（等待用户验收） |
| Approval | 用户指令「按顺序发展把」（2026-11-28），§12+ 第 3 项 |
| 任务单元 | `memory` 表、词面召回、上下文注入、`/memory` API |
| 不包含 | 向量检索/Embedding、自动抽取记忆、记忆摘要与冲突合并、记忆编辑 UI |

**Done Contract**：用户可保存全局或会话级记忆；每次 run 只注入与目标词面相关的少量记忆
（`plan.memory_used` 可追溯、`last_used_at` 更新）；无相关记忆时指令不增长；`ruff`/`pytest` 全绿。

---

## 1. 目标与验收

1. `memory` 表：`scope`（global/conversation）、`scope_id`、`kind`、`content`、`tags`、`created_by`、`last_used_at`；`scope_id` 与 `scope` 由 CHECK 保证一致。
2. `POST /api/v1/memory` 创建；`scope=conversation` 必须带存在的 `conversation_id`，否则 `404`；非法 `scope` 由 Pydantic 拒绝（422）。
3. `GET /api/v1/memory` 列表（可按 scope/conversation 过滤）；`GET /api/v1/memory/search?q=` 返回排序后的召回结果；`DELETE /api/v1/memory/{id}` 删除（不存在 → 404）。
4. 召回为纯词面打分：拉丁词 + 中文二元组；按共享 token 数降序、同级新者优先；无共享 token 则不召回。
5. `ContextAssembler` 在「用户偏好」之后插入「长期记忆」段落（可裁剪），条数上限 `memory_max_items`。
6. `plan` 事件含 `memory_used`（记忆 id 列表）；被召回条目的 `last_used_at` 更新。
7. 记忆检索异常不得中断 run（记录日志并降级为空）。
8. `/config` 暴露 `features.memory=true` 与 `memory.{enabled,max_items}`。
9. `ruff`、`pytest` 全绿（含既有 365 项）。

---

## 2. In / Out of Scope

**In**：迁移 `0009`、`Memory` 模型、`modules/memory/*`、上下文注入、`/memory` 路由、配置项、单元/集成测试、文档回写。

**Out**：向量库、LLM 自动写入记忆、跨会话用户画像、记忆编辑 UI、TTL/归档策略。

---

## 3. Research Findings

| 事实 | 结论 | 影响 |
| --- | --- | --- |
| `ContextAssembler` 已按固定优先级拼指令并支持 `droppable` 裁剪 | 记忆作为可裁剪段插入即可 | 不动主链路 |
| 运行计划事件已含 `tools`/`warnings`/`budget` | 追加 `memory_used` 成本极低 | 可追溯 |
| 平台无向量库、无额外基础设施 | 词面召回是唯一零依赖方案 | 明确不做 Embedding |
| 中文无空格 | 需要 CJK 二元组切分 | `tokenize()` 同时处理拉丁与 CJK |

---

## 4. Open Questions（默认决策）

| # | 问题 | 决策 |
| --- | --- | --- |
| Q1 | 召回算法 | 词面重叠计数（拉丁词 + CJK 二元组），不引入依赖 |
| Q2 | 召回范围 | global + 当前会话；不跨会话检索其他会话记忆 |
| Q3 | 写入来源 | 仅用户显式 API；Agent 不自动写记忆 |
| Q4 | 冲突/去重 | 不做合并；重复内容由用户删除 |
| Q5 | 上限 | 每 run 最多 `memory_max_items`（默认 5）条，段落可被预算裁剪 |
| Q6 | UI | 本期只提供 API（8 个视图不变） |

---

## 5. Plan（Contract）

### 5.1 File Changes

| 路径 | 动作 | 内容 |
| --- | --- | --- |
| `src/reportify/db/migrations/versions/0009_memory.py` | 新增 | `memory` 表、CHECK、索引 |
| `src/reportify/db/models/memory.py` | 新增 | `Memory` 实体 |
| `src/reportify/modules/memory/{__init__,schemas,retrieval,service}.py` | 新增 | 契约、词面召回、CRUD |
| `src/reportify/modules/runtime/context.py` | 更新 | 召回 + 注入段 + `ContextBundle.memory_used` |
| `src/reportify/modules/runtime/runtime.py` | 更新 | `plan` 事件 `memory_used` |
| `src/reportify/api/routes/memory.py` | 新增 | 四个端点 |
| `src/reportify/api/{app,deps}.py`、`routes/system.py` | 更新 | 装配、依赖、能力位 |
| `src/reportify/core/config.py` | 更新 | `memory_enabled`、`memory_max_items` |
| `tests/unit/test_memory_retrieval.py`、`tests/integration/test_memory_api.py` | 新增 | 召回与 API/注入 |
| `tests/integration/conftest.py` | 更新 | TRUNCATE 加 `memory` |

### 5.2 关键签名

```python
def tokenize(text: str) -> set[str]: ...
def rank(query: str, memories: list[Memory], *, limit: int = 5) -> list[MemoryItem]: ...

class MemoryService:
    async def add(self, payload: MemoryCreate) -> MemoryRead: ...
    async def list(self, *, scope=None, conversation_id=None, limit=50, offset=0) -> list[MemoryRead]: ...
    async def delete(self, memory_id: UUID) -> None: ...
    async def search(self, query, *, conversation_id=None, limit=None) -> list[MemoryItem]: ...
```

### 5.3 行为细节

- 召回：`overlap = |tokens(query) ∩ tokens(content + tags)|`；`<=0` 丢弃；否则按 `(-overlap, -created_at)` 排序取前 N。
- 注入段：`## 长期记忆（用户确认过的偏好与事实）` + `- [kind] content`，位置在「用户偏好」之后、「当前分析任务」之前，`droppable=True`。
- 仅对实际注入的条目写 `last_used_at`，同一次查询一次提交。
- `MemoryService.search` 异常在 `ContextAssembler._recall` 内捕获，`warnings` 不新增（避免噪声），仅日志。
- `memory_enabled=false` 时 `ContextAssembler` 不持有 MemoryService，行为与 M9 一致。

### 5.4 Checklist

- [x] 1. 迁移 + 模型 + 服务。
- [x] 2. 词面召回与单测。
- [x] 3. 上下文注入与 `plan.memory_used`。
- [x] 4. `/memory` API、配置与能力位。
- [x] 5. 全量回归。
- [x] 6. Reverse Sync：01/02/05/07/08/09 与 Spec。

---

## 6. 验证方式

| 项 | 命令 / 操作 | 期望 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | 通过 |
| 召回单测 | `pytest tests/unit/test_memory_retrieval.py` | 分词、排序、无重叠丢弃、limit |
| 集成 | `pytest tests/integration/test_memory_api.py` | CRUD、会话隔离、注入与 `last_used_at` |
| 全量 | `uv run pytest -q` | 全绿 |

---

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 词面召回漏召回中文近义 | 记录为已知限制；tags 可补充别名 |
| 记忆污染指令 | 段落可裁剪、有上限、明确标注来源为用户 |
| 记忆检索拖慢 run | 候选上限 500、只取 top-N、异常降级 |
| 会话删除后残留 | `scope_id` FK `CASCADE` |

---

## 8. Execute Log

| # | 动作 | 结果 |
| --- | --- | --- |
| 1 | 迁移 | `0009_memory`：表 + scope/kind/一致性强 CHECK + 两个索引；降级/升级往返通过 |
| 2 | 模型/服务 | `Memory`；`MemoryService.add/list/delete/search`；每次召回只更新命中条目的 `last_used_at` |
| 3 | 召回 | `tokenize()`（拉丁词 + CJK 二元组）、`rank()`（重叠数降序、新者优先） |
| 4 | 注入 | `ContextAssembler` 新增 memory 段（可裁剪）+ `ContextBundle.memory_used` |
| 5 | 事件 | `plan.memory_used` 记录 id，可追溯 |
| 6 | API | `GET/POST /memory`、`GET /memory/search`、`DELETE /memory/{id}` |
| 7 | 配置 | `memory_enabled`、`memory_max_items`；`/config` 暴露状态 |
| 8 | 测试 | 6 个召回单测 + 4 个集成；全量 375 passed / 1 skipped |

## 9. Verification Evidence

| 项 | 命令 / 操作 | 结果 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | `All checks passed!` |
| 全量测试 | `REPORTIFY_TEST_DATABASE_URL=… uv run pytest -q` | `375 passed, 1 skipped in 121.96s` |
| 召回单测 | `pytest tests/unit/test_memory_retrieval.py` | 6 passed（分词/排序/无关丢弃/空查询/limit/标签） |
| API 与注入 | `pytest tests/integration/test_memory_api.py` | 4 passed（CRUD、会话隔离、非法 scope、注入与 `last_used_at`） |
| 注入证据 | 目标含「最近 30 天」的 run | `plan.memory_used == [memory_id]` |
| 无关查询 | `q=配色方案` | 返回 `[]`（不注入噪声） |
| 迁移往返 | `alembic downgrade 0008` → `upgrade head` | 两向成功；`alembic current` = `0009 (head)` |

## 10. Plan-Execution Diff

| 项 | 计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| 记忆段落命名 | 计划「长期记忆」 | 同，附「用户确认过的偏好与事实」 | 强调来源，降低模型误用 |
| 召回失败 | 计划降级为空 | 同，且不写入 `warnings` | 避免每轮 run 噪声 |
| 视图 | 计划不做 UI | 同（API-only） | 8 视图契约不变，避免范围蔓延 |
| `last_used_at` | 计划记录 | 同，仅命中条目 | 便于审计「为什么注入」 |

## 11. Review Verdict

| 轴 | 检查项 | 结论 | 证据 |
| --- | --- | --- | --- |
| Axis-1 | 目标与验收明确 | PASS | §1（9 条） |
| Axis-1 | 逐条验证 | PASS | §9（7 项证据） |
| Axis-2 | Checklist 完成 | PASS | §5.4 |
| Axis-2 | 偏差记录 | PASS | §10（4 项） |
| Axis-3 | 安全 | PASS | 仅用户显式写入；注入段可裁剪；无自动写记忆；检索异常降级 |
| Axis-3 | 正确性 | PASS | 375 项测试；真实 run 的 `memory_used` 与 `last_used_at` 核对 |
| Axis-3 | 可维护性 | PASS | 召回为纯函数，服务只管取数与写入 |
| Axis-3 | 未覆盖项 | PARTIAL | 无向量召回、无自动抽取、无记忆 UI、无冲突合并 |

**Overall Verdict：PASS（附后续项）**。`MemoryProvider` 从占位变为可用能力，且不引入新依赖。

## 12. Gate

- 当前 `Review`，等待用户验收。
- 后续 §12+：OAuth 2.1、审批超时自动取消。
