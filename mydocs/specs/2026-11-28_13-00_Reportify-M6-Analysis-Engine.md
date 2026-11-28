# Reportify M6 · Analysis Engine — Spec

> 层级：Feature Spec（实现阶段，§12+ 功能按契约先行）
> 依据：`docs/architecture/03-tooling-and-mcp.md` §5、`01-system-overview.md` §4（模块 13）、`09-engineering.md` §12。
> 前置：M0–M5 已实现（281 项测试通过）。本里程碑只实现 03 §5 已定义的 5 个 `builtin_analysis` 工具契约。

---

## 0. 状态

| 字段 | 值 |
| --- | --- |
| Phase | `Review` |
| Status | `IMPLEMENTED`（等待用户验收） |
| Approval | 用户指令「继续」（2026-11-28），延续完成剩余能力 |
| 任务单元 | 趋势 / 分布 / 周期对比 / 异常检测 / 相关性 五个分析工具 + 共享的 pandas 计算层 |
| 不包含 | 报告正式渲染器（ECharts 需联网获取，另议）、Memory、Scheduler、自动洞察规划 |

**Done Contract**：5 个分析工具可被 Agent 调用，返回带 `lineage` 的结构化结果；
算法有单元测试（合成数据），工具链在真实 PostgreSQL 上有集成测试；`ruff` 与 `pytest` 全绿。

---

## 1. 目标与验收

1. 新增 `builtin.analyze_trend`、`analyze_distribution`、`compare_periods`、`detect_anomalies`、
   `analyze_correlation`，`kind='builtin_analysis'`、`risk_level='read'`，启动时幂等注册并默认授权（与 M2 内置工具一致）。
2. 每个工具只接受 `data_source_id` 与结构化参数，**不接受原始 SQL**；取数走 `QuerySpec` 与 `SafeQueryBuilder`。
3. 结果统一为 `AnalysisResult`（Pydantic）：`kind`、`summary`、`metrics`、`series`/`points`、`warnings`、`lineage`。
4. 计算全部由 pandas 完成：LLM 只拿到汇总值与有限点集（≤ 500 点），不拿原始行。
5. 每个工具在 `lineage.definition` 里写明口径（聚合方式、时间粒度、样本量、阈值参数）。
6. 空数据、单点、全空列、非数值列等边界返回 `ok=True` 的空结果或 `ToolResult.failure`，不抛未处理异常。
7. 单元测试覆盖 5 个算法的正常与边界；集成测试覆盖工具在真实表上的调用与 lineage。
8. `ruff`、`pytest` 全绿（含原有 281 项）。

---

## 2. In / Out of Scope

**In**：`modules/analysis/`（schemas + compute）、5 个工具、注册与授权、单元/集成测试。

**Out**：报告渲染器、图表前端、自动选择分析方法的规划器、更大样本的分块计算、Memory。

---

## 3. Research Findings

| 事实 | 结论 | 影响 |
| --- | --- | --- |
| 工具契约 | 03 §5 已定义 5 个分析工具的输入/输出与「必须带 lineage」 | 不重新设计接口 |
| 取数 | `ConnectorRegistry.get()` → `QuerySpec` → `ResultSet`（含 lineage/snapshot） | 分析工具复用 M1 通道 |
| 聚合能力 | `QuerySpec` 支持 `group_by` + `count/sum/avg/min/max/stddev`，**不支持 `date_trunc`** | 时间分桶在 pandas 内完成 |
| 数据量 | 数据源 `max_rows` 默认 10,000；Pandas ≤100 万行 | 先取样本再计算，口径写明样本量 |
| 依赖 | `pandas` 已安装（3.1.1）、`numpy` 已随依赖安装 | 无需新增依赖 |
| ECharts | 本机 CDN 不可达、仓库无本地副本 | 渲染器留待后续；本里程碑不产出图表 |

---

## 4. Open Questions（默认决策）

| # | 问题 | 决策 |
| --- | --- | --- |
| Q1 | 取数方式 | 取原始列（限 `max_rows`）后在 pandas 分桶/聚合；口径里写明「样本 ≤ N 行，按 X 分桶」 |
| Q2 | 时间粒度 | `hour/day/week/month`；按 UTC 归一后 `resample` |
| Q3 | 数值列判定 | 由 `normalized_type == 'numeric'` 且 pandas 可转 float |
| Q4 | 异常检测方法 | `zscore`（默认，阈值 3）与 `iqr`（1.5 倍四分位距） |
| Q5 | 相关性方法 | `pearson`（默认）与 `spearman` |
| Q6 | 结果上限 | series ≤ 500 点；相关性矩阵 ≤ 20 列 |
| Q7 | 聚合函数 | trend/summary 用 `sum`/`avg`/`count` 三选一，默认 `sum` |

---

## 5. Plan（Contract）

### 5.1 File Changes

| 路径 | 动作 | 内容 |
| --- | --- | --- |
| `src/reportify/modules/analysis/__init__.py` | 新增 | 导出 compute 函数与 schemas |
| `src/reportify/modules/analysis/schemas.py` | 新增 | `AnalysisResult`、`SeriesPoint`、`AnalysisSeries`、`AnomalyPoint` |
| `src/reportify/modules/analysis/compute.py` | 新增 | 5 个纯函数（输入 DataFrame，输出 AnalysisResult 片段），无 I/O |
| `src/reportify/modules/analysis/frames.py` | 新增 | 从 `ResultSet` 构造 DataFrame、类型归一、时间解析 |
| `src/reportify/modules/tools/registry.py` | 更新 | 新增 5 个 `ToolSpec` |
| `src/reportify/modules/tools/builtin.py` | 更新 | 新增 5 个工具函数（取数 → compute → ToolResult） |
| `src/reportify/modules/tools/__init__.py` | 更新 | 导出新工具（随 `BUILTIN_FUNCTIONS` 自动） |
| `tests/unit/test_analysis_compute.py` | 新增 | 5 个算法的正常/边界 |
| `tests/integration/test_analysis_tools.py` | 新增 | 真实表上的工具调用、lineage、边界 |

### 5.2 关键签名

```python
# compute.py（纯函数）
def trend(frame, *, time_column, metric_column, granularity, agg="sum") -> TrendOutcome: ...
def distribution(frame, *, field, bins=10) -> DistributionOutcome: ...
def compare_periods(frame, *, metric_column, time_column, current, previous, agg="sum") -> ComparisonOutcome: ...
def detect_anomalies(frame, *, metric_column, time_column, method="zscore", threshold=3.0) -> AnomalyOutcome: ...
def correlation(frame, *, fields, method="pearson") -> CorrelationOutcome: ...

# builtin.py（工具）
async def analyze_trend(ctx, data_source_id, table, metric, time_column,
                        granularity="day", agg="sum", start=None, end=None) -> ToolResult: ...
```

### 5.3 行为细节

- 取数：`QuerySpec(table=table, columns=[time_column, metric], time_range=..., limit=max_rows)`；
  时间范围用 `TimeRange`，聚合与分桶在 pandas 完成。
- `trend`：按粒度 `resample`，`agg` 聚合；`metrics` 含 `points`、`first`、`last`、`change_pct`、
  `slope_per_bucket`（最小二乘）、`volatility`（逐点变化率标准差）；空/单点返回 `warnings`。
- `distribution`：数值列 → 等宽直方图（默认 10 箱）+ `mean/std/min/max/skew/null_ratio`；
  非数值列 → Top 10 频次；`distinct_count`。
- `compare_periods`：两段各自聚合 → `current`、`previous`、`diff`、`change_pct`；任一段为空值返回 `None` 并告警。
- `detect_anomalies`：`zscore` 用均值/标准差，`iqr` 用 Q1/Q3；返回异常点（时间、值、分数）与阈值参数。
- `correlation`：数值列两两相关矩阵；`abs` 排序取前 10 对；样本 < 3 返回空并告警。
- 所有工具：`degraded` 情况（样本截断）在 `warnings` 与 `lineage.definition` 注明。
- 结果 `series` 截断到 500 点，超出置 `truncated`。

### 5.4 Checklist

- [x] 1. schemas + frames + compute（纯函数）+ 单测。
- [x] 2. 5 个 ToolSpec 注册与 5 个工具实现。
- [x] 3. 集成测试（真实表、lineage、边界、未知列）。
- [x] 4. 全量回归（M0–M5 不回归）。
- [x] 5. Reverse Sync：更新 03 §5、09 §12 与 Spec。

---

## 6. 验证方式

| 项 | 命令 / 操作 | 期望 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | 通过 |
| 单元测试 | `pytest tests/unit/test_analysis_compute.py` | 5 个算法正常 + 边界全通过 |
| 集成测试 | `pytest tests/integration/test_analysis_tools.py` | 工具返回 `ok=true`、有 lineage、点集 ≤500 |
| 全量 | `uv run pytest -q` | 全绿（含原有 281 项） |
| 注册 | 查看 `tool_definition` | 5 个 `builtin_analysis` 工具、默认授权 |
| 边界 | 空表/单行/非数值列 | 不抛异常，返回空结果 + 告警 |

---

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 大表拉取过多 | 复用数据源 `max_rows`；`warnings` 与口径注明样本量 |
| 时区/类型差异 | 统一转 UTC、数值 `to_numeric(errors="coerce")` |
| pandas 版本行为差异 | 只用稳定 API（`resample`、`describe`、`corr`、`skew`） |
| 结果过大 | series ≤500、相关性 ≤20 列 |
| 分析结果被误读 | `definition` 写明聚合与口径；不推断业务语义 |

---

## 8. Execute Log

| # | 动作 | 结果 |
| --- | --- | --- |
| 1 | 计算层 | `modules/analysis/`：`schemas.py`、`frames.py`（类型/时间归一）、`compute.py`（5 个纯函数） |
| 2 | 注册 | `ToolRegistry` 新增 5 个 `builtin_analysis` 规格；启动幂等注册、默认全局授权（与 M2 一致） |
| 3 | 工具 | `builtin.py` 新增 5 个工具；共用 `_load_analysis_frame`（`QuerySpec` + 10k 样本上限 + lineage + 快照归属） |
| 4 | 边界 | 空/单点/常量序列/非数值列/字段不存在/非法粒度均返回结构化结果或 `ToolResult.failure`，不抛未处理异常 |
| 5 | 测试 | 16 个单元（5 算法 + 边界）+ 7 个集成（真实表、lineage、错误路径） |
| 6 | 回写 | 本节、03 §5、09 §12 |

## 9. Verification Evidence

| 项 | 命令 / 操作 | 结果 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | `All checks passed!` |
| 全量测试 | `REPORTIFY_TEST_DATABASE_URL=… uv run pytest -q` | `304 passed, 1 skipped in 88.14s` |
| 单元测试 | `pytest tests/unit/test_analysis_compute.py` | 16 passed |
| 集成测试 | `pytest tests/integration/test_analysis_tools.py` | 7 passed |
| 注册 | `BUILTIN_SPECS` / `BUILTIN_FUNCTIONS` | 11 个规格与 11 个函数一一对应，5 个 `builtin_analysis` |
| trend | 真实表 `events`（avg duration, day） | run `succeeded`；审计 `succeeded`；摘要含「个点」 |
| distribution | `duration`，5 箱 | 审计 `succeeded`；摘要含「有效值」 |
| compare_periods | 近 1 天 vs 前 1 天 | 审计 `succeeded`；摘要含「上期」 |
| anomalies | `duration`，zscore | 审计 `succeeded`；摘要含「异常点」 |
| correlation | `duration` vs `id` | 审计 `succeeded`；摘要含「相关」，最强对输出 |
| 未知字段 | `metric=nope` | 审计 `failed`，`invalid_argument`/`upstream_error`，run 不崩溃 |
| 非法粒度 | `granularity=minute` | 查询前即拒绝，摘要含 `granularity` |

## 10. Plan-Execution Diff

| 项 | 计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| 取数 | 每工具各自构造 `QuerySpec` | 抽出 `_load_analysis_frame` 共用 | 统一样本上限、告警与快照归属 |
| `time_range` 过滤 | 接口未定 | 趋势/对比工具支持可选 `start`/`end`，映射为 `TimeRange` | 让「按范围分析」可用，仍不接受原始 SQL |
| 分布/相关性参数 | 无时间参数 | 不接受 `time_column`（Pydantic 会拒绝多余参数） | 契约只包含文档列出的参数 |
| 时间解析 | `pd.to_datetime` 默认 | `format="mixed"` | 消除 pandas 的格式推断告警 |
| 单元测试数量 | 计划 5 算法 | 16 个（含边界） | 边界行为需要锁定 |
| 图表产出 | 计划外 | 无 | ECharts 无法离线获取；本里程碑只产出结构化结果，渲染器另议 |

## 11. Review Verdict

| 轴 | 检查项 | 结论 | 证据 |
| --- | --- | --- | --- |
| Axis-1 | 目标与验收标准明确 | PASS | §1 |
| Axis-1 | 验收项逐条验证 | PASS | §9（8 条验收对应 12 项证据） |
| Axis-2 | Checklist 1–5 完成 | PASS | §5.4 |
| Axis-2 | 偏差已记录 | PASS | §10（6 项） |
| Axis-3 | 安全 | PASS | 只读工具；不接受 SQL；样本上限；结果点数上限；口径写明样本量 |
| Axis-3 | 正确性 | PASS | 304 项测试；真实 PostgreSQL 表 |
| Axis-3 | 可维护性 | PASS | 计算与 I/O 分离（`compute` 纯函数可单测） |
| Axis-3 | 未覆盖项 | PARTIAL | 无图表渲染、无自动选择方法、无分块大样本计算 |

**Overall Verdict：PASS（附后续项）**。03 §5 的 11 个内置工具中 11 个落地（`generate_report` 仍为占位渲染）。

## 12. Gate

- 当前 `Review`，等待用户验收。
- 下一步候选：报告正式渲染器（需先解决 ECharts 离线依赖）、Scheduler/ARQ、Memory。
