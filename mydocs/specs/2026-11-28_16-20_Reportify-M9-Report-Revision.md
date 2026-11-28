# Reportify M9 · Report Revision — Spec

> 层级：Feature Spec（§12+ 功能按契约先行）
> 依据：`05-conversation-task.md` §8（历史 `report_ref` 不覆盖）、`08-data-model.md` §6.18、`07-api-and-ui.md` §7.1（报告库）。
> 前置：M0–M8 已实现（358 项测试通过）。`report_ref` 目前只有一份 HTML 与 lineage，无版本与对比。

---

## 0. 状态

| 字段 | 值 |
| --- | --- |
| Phase | `Review` |
| Status | `IMPLEMENTED`（等待用户验收） |
| Approval | 用户指令「按顺序发展把」（2026-11-28），§12+ 第 2 项 |
| 任务单元 | 报告版本号与父链、结构化 schema 落库、版本列表与两版 diff、报告库展示 |
| 不包含 | 版本回滚/分支合并、报告在线编辑、逐像素 HTML diff、PDF 导出 |

**Done Contract**：同一 Task 的每次报告生成都留下带 `version` 与 `parent_report_id` 的新 `report_ref`；
`GET /reports/{id}/revisions` 返回完整链；`GET /reports/{id}/diff` 给出结构化差异；历史版本不被覆盖。

---

## 1. 目标与验收

1. `report_ref` 新增 `version`（从 1 递增）、`parent_report_id`、`schema`（经校验的 Report Schema JSON）。
2. 同一 Task 第二次生成报告时 `version=2`、`parent_report_id` 指向上一版；上一版 HTML 与行不变。
3. `GET /api/v1/reports/{id}/revisions` 返回该报告所在版本的完整链（升序，含版本号、标题、运行、时间）。
4. `GET /api/v1/reports/{id}/diff` 默认与父版本比较，可用 `?against=<report_id>` 指定任意历史版本。
5. diff 为结构化 JSON：标题/摘要变化、章节增删、KPI 值变化、图表 series/点数变化、表格行数变化、文本变化；无差异时 `identical=true`。
6. 无父版本时 diff 返回 `409 conflict`；`schema` 缺失的历史行为 `409`（不猜测差异）。
7. 报告库视图显示版本号，并可查看版本链与「与上一版对比」结果。
8. `ruff`、`pytest` 全绿（含既有 358 项）。

---

## 2. In / Out of Scope

**In**：迁移 `0008`、`ReportRef` 字段、仓储 `latest_for_task`/`chain`、`modules/reports/diff.py`、服务版本化与 diff、
两个 API 端点、报告库视图、单元/集成测试、文档回写。

**Out**：回滚到历史版本、分支/合并、并发写同一 Task（由单活跃 Run 保证）、HTML 文本 diff。

---

## 3. Research Findings

| 事实 | 结论 | 影响 |
| --- | --- | --- |
| `report_ref` 只存 HTML 路径与 lineage | 无 schema 无法可靠 diff | 落库 `schema` JSONB |
| 报告同一 Task 多次生成会覆盖 `analysis_task.report_ref_id` | 历史行仍在 | 只需补版本链 |
| `generate_report` 每 run 只能一次 | 版本来自 run 边界 | 版本 = 该 Task 已生成报告数 + 1 |
| 渲染器输入是 `section.model_dump(mode="json")` | diff 可直接比对同一结构 | 纯函数即可，不依赖渲染 |

---

## 4. Open Questions（默认决策）

| # | 问题 | 决策 |
| --- | --- | --- |
| Q1 | 版本号来源 | 按 Task 内顺序（`max(version)+1`），不全局 |
| Q2 | 老数据 | `schema` 为 NULL；diff 明确拒绝而不是猜测 |
| Q3 | 对比默认对象 | 父版本；`?against=` 可跨版本 |
| Q4 | 是否保留 HTML 历史 | 保留（文件已按 report_id 命名，天然不覆盖） |
| Q5 | 回滚 | 不提供写操作；「回到旧版」以新建 Task 重新生成为准（05 §8） |

---

## 5. Plan（Contract）

### 5.1 File Changes

| 路径 | 动作 | 内容 |
| --- | --- | --- |
| `src/reportify/db/migrations/versions/0008_report_revision.py` | 新增 | 三列 + `(task_id, version)` 索引 |
| `src/reportify/db/models/report.py` | 更新 | `version`、`parent_report_id`、`schema` |
| `src/reportify/db/repositories/reports.py` | 更新 | `latest_for_task`、`chain_for_report`、create 参数 |
| `src/reportify/modules/reports/diff.py` | 新增 | `diff_schemas()` 纯函数 |
| `src/reportify/modules/reports/schemas.py` | 更新 | `ReportRevisionRead`、`ReportDiff` 等 |
| `src/reportify/modules/reports/service.py` | 更新 | 版本化写入、`revisions()`、`diff()` |
| `src/reportify/api/routes/reports.py` | 更新 | `/revisions`、`/diff` |
| `src/reportify/templates/reports.html`、`static/views/reports.js` | 更新 | 版本列 + 版本/对比面板 |
| `tests/unit/test_report_diff.py` | 新增 | 差异化纯函数 |
| `tests/integration/test_report_revisions.py` | 新增 | 版本链、diff 端点、无父版本 |

### 5.2 关键签名

```python
def diff_schemas(base: dict, target: dict, *, base_version: int, target_version: int) -> ReportDiff: ...

class ReportService:
    async def revisions(self, report_id: UUID) -> list[ReportRevisionRead]: ...
    async def diff(self, report_id: UUID, *, against: UUID | None = None) -> ReportDiff: ...
```

### 5.3 行为细节

- 版本化：`generate()` 在同一 Session 内取 `latest_for_task()` → `version = parent.version + 1`，写入 `parent_report_id` 与 `schema`。
- diff 匹配规则：章节按 `id`；KPI 按 `label`；图表/表格按 `title`；文本按同章节内位置。
- KPI 值变化只比较 `value`；`definition`/`lineage_refs` 变化不计入（口径变化由文本/表格体现）。
- 图表差异报告 `series` 数量与总点数；表格只报告行数。
- `identical`：所有列表为空且标题/摘要未变。
- 文本变化在响应中保留原文（≤4000 字符，Schema 已限制）。

### 5.4 Checklist

- [x] 1. 迁移与模型。
- [x] 2. diff 纯函数与单测。
- [x] 3. 版本化写入与两个端点。
- [x] 4. 视图与测试。
- [x] 5. 全量回归。
- [x] 6. Reverse Sync：05 / 07 / 08 / 09 与 Spec。

---

## 6. 验证方式

| 项 | 命令 / 操作 | 期望 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | 通过 |
| diff 单测 | `pytest tests/unit/test_report_diff.py` | KPI/图表/表格/文本/章节增删 |
| 集成 | `pytest tests/integration/test_report_revisions.py` | v1→v2 链、默认 diff、`?against=`、409 |
| 全量 | `uv run pytest -q` | 全绿 |

---

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 并发生成两条同版本 | 单会话单活跃 Run；版本仅用于展示，不承担唯一性语义 |
| 老报告无法 diff | 显式 409 + 文案，不伪造差异 |
| diff 体积 | 仅结构化摘要，不返回整份 schema |
| 版本链断环 | 父指针 `SET NULL`，链遍历最多 100 跳，缺环即停止 |

---

## 8. Execute Log

| # | 动作 | 结果 |
| --- | --- | --- |
| 1 | 迁移 | `0008_report_revision`：`version` / `parent_report_id` / `schema` 三列 + `(task_id, version)` 索引；降级/升级往返通过 |
| 2 | 模型/仓储 | `ReportRef` 三字段；`latest_for_task()`；`create_report()` 支持 schema/version/parent |
| 3 | diff | `modules/reports/diff.py` 纯函数：标题/摘要、章节增删、KPI、图表、表格、文本 |
| 4 | 服务 | `generate()` 计算版本与父链；`revisions()` 走父指针；`diff()` 默认父版本、可 `?against=` |
| 5 | API | `GET /reports/{id}/revisions`、`GET /reports/{id}/diff`；`ReportRefView` 暴露版本 |
| 6 | 视图 | 报告库增加「版本」列与「版本/对比」面板（纯文本渲染，无内联脚本） |
| 7 | 测试 | 5 个 diff 单测 + 2 个版本链集成；全量 365 passed / 1 skipped |
| 8 | 回写 | 本 Spec、01 §4、05 §8、07 §5.5/§7.1、08 §6.18、09 §11 |

## 9. Verification Evidence

| 项 | 命令 / 操作 | 结果 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | `All checks passed!` |
| 全量测试 | `REPORTIFY_TEST_DATABASE_URL=… uv run pytest -q` | `365 passed, 1 skipped in 125.70s` |
| diff 单测 | `pytest tests/unit/test_report_diff.py` | 5 passed（相同、KPI、章节增删、图表/表格、文本/标题） |
| 版本链 | `pytest tests/integration/test_report_revisions.py` | 2 passed |
| 版本写入 | 查询 `/reports` | v1 `parent=null`，v2 `parent=v1`；两次生成后旧 HTML 仍可下载 |
| 差异内容 | `GET /reports/{v2}/diff` | `sections_added=["trend"]`、KPI `20→25`、图表点数 `2→3` |
| 指定对比 | `?against={v1}` | 与默认结果一致 |
| 无父版本 | `GET /reports/{v1}/diff` | `409 conflict`；未知 `against` → `404` |
| 迁移往返 | `alembic downgrade 0007` → `upgrade head` | 两向成功；`alembic current` = `0008 (head)` |

## 10. Plan-Execution Diff

| 项 | 计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| 老数据 `schema` | 计划可空 | 同，`None` 时 diff 返回 409 | 不伪造差异 |
| 第二次运行脚本 | 未预见 | 测试脚本首位加占位步骤 | 05 §9：同 Task 新 Run 复用上一 Run 的 `history_blob`，脚本模型从第 2 轮开始 |
| 版本唯一性 | 计划不加唯一约束 | 同 | 多 Run 串行由单活跃 Run 保证，避免迁移失败风险 |
| diff 输出 | 计划含「指标变化」 | 另加图表 series/点数、表格行数 | 让图表与表格变化也可解释 |
| 视图 | 计划仅加版本列 | 另加版本/对比面板 | 不打开报告也能看到差异 |

## 11. Review Verdict

| 轴 | 检查项 | 结论 | 证据 |
| --- | --- | --- | --- |
| Axis-1 | 目标与验收明确 | PASS | §1（8 条） |
| Axis-1 | 逐条验证 | PASS | §9（9 项证据） |
| Axis-2 | Checklist 完成 | PASS | §5.4 |
| Axis-2 | 偏差已记录 | PASS | §10（5 项） |
| Axis-3 | 安全 | PASS | diff 只读、无 HTML 解析、无 LLM 生成；文本经 `textContent` 渲染 |
| Axis-3 | 正确性 | PASS | 365 项测试；真实两次生成 + 端点核对；迁移往返 |
| Axis-3 | 可维护性 | PASS | diff 为纯函数，服务只做取数与链遍历 |
| Axis-3 | 未覆盖项 | PARTIAL | 无回滚/分支、无 HTML 级 diff、无并发同 Task 版本冲突测试 |

**Overall Verdict：PASS（附后续项）**。报告从「单文件产物」升级为「可追溯的版本链 + 可解释差异」。

## 12. Gate

- 当前 `Review`，等待用户验收。
- 后续 §12+：Memory、OAuth 2.1、审批超时。
