# Reportify M7 · Report Renderer — Spec

> 层级：Feature Spec（实现阶段，§12+ 功能按契约先行）
> 依据：`docs/architecture/07-api-and-ui.md` §7.2、§9；`03-tooling-and-mcp.md` §5（`generate_report`）；`09-engineering.md` §12。
> 前置：M0–M6 已实现（304 项测试通过）。M2 的占位渲染器由本里程碑替换为正式渲染器。

---

## 0. 状态

| 字段 | 值 |
| --- | --- |
| Phase | `Review` |
| Status | `IMPLEMENTED`（等待用户验收） |
| Approval | 用户指令「继续」（2026-11-28），延续完成剩余能力 |
| 任务单元 | 单文件 HTML 报告渲染器：内联 ECharts + ReportSchema 四类 block + lineage 区块 |
| 不包含 | 报告版本树、在线筛选、图表下钻、模板主题系统、导出 PDF |

**Done Contract**：`generate_report` 产出的 HTML 是可离线打开的单文件，含可交互 ECharts 图表；
所有文本经转义；报告引用可追溯；`ruff` 与 `pytest` 全绿。

---

## 1. 目标与验收

1. 渲染器 `renderer="echarts-v1"`：产出单个 HTML 文件，内联 ECharts 5.5.0（Apache-2.0，带许可头），不依赖 CDN 与管理台。
2. `kpi` / `table` / `chart` / `text` 四类 block 全部渲染；`chart` 支持 `line`/`bar`/`pie`/`scatter`。
3. 图表数据以 ECharts option 内联，页面加载时 `echarts.init` 渲染；无图表库时页面仍能显示表格化数据（降级）。
4. 所有来自 ReportSchema 的文本经 Jinja2 自动转义；`text`/`title` 中出现 `<script>` 不得执行。
5. lineage 区块列出 `dataset_snapshot` 的 SQL、参数、行数与口径，作为「数据来源」证明。
6. 下载响应对报告文件使用专属 CSP（允许内联脚本与样式），不影响管理台页面的严格 CSP。
7. `report_ref.renderer` 记录 `echarts-v1`；占位渲染器与「占位」横幅移除。
8. `ruff`、`pytest` 全绿（含既有 304 项，报告相关断言随实现更新）。

---

## 2. In / Out of Scope

**In**：`static/vendor/echarts.min.js`（vendored）、`templates/report.html.j2`、`renderer.py` 重写、
`ReportService` 接线、下载 CSP、单元/集成测试、文档。

**Out**：模板主题、PDF 导出、图表联动、报告版本树、在线筛选。

---

## 3. Research Findings

| 事实 | 结论 | 影响 |
| --- | --- | --- |
| ECharts 获取 | jsdelivr 不可达；unpkg 可直连，`echarts@5.5.0` 1,029,203 字节，含 Apache-2.0 头 | 可 vendored 到包内 |
| 现有渲染 | M2 占位模板把 chart 渲染成表格 +「非最终」横幅 | 本里程碑替换 |
| ReportSchema | 四类 block 已由 Pydantic 校验，`lineage_refs` 必填 | 渲染器无需再校验结构 |
| CSP | 中间件对所有响应加严格 CSP；`FileResponse` 可自带头覆盖（中间件用 `setdefault`） | 下载响应单独放行内联 |
| 单文件体积 | 内联 ECharts ≈1MB/份报告 | 可接受；在口径中说明 |

---

## 4. Open Questions（默认决策）

| # | 问题 | 决策 |
| --- | --- | --- |
| Q1 | 内联还是外链 ECharts | **内联**（单文件可离线打开）；体积代价记录在案 |
| Q2 | 报告 CSP | `default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'` |
| Q3 | 无 JS 环境 | 图表下方保留表格化数据（降级） |
| Q4 | 主题 | 内置一套浅色样式；主题系统留待后续 |
| Q5 | `text` block | 保留换行（`white-space: pre-wrap`），仍转义 |

---

## 5. Plan（Contract）

### 5.1 File Changes

| 路径 | 动作 | 内容 |
| --- | --- | --- |
| `src/reportify/static/vendor/echarts.min.js` | 新增 | ECharts 5.5.0（Apache-2.0，保留许可头） |
| `src/reportify/templates/report.html.j2` | 新增 | 单文件报告模板（内联 ECharts、四类 block、lineage） |
| `src/reportify/templates/report_placeholder.html.j2` | 删除 | 占位渲染下线 |
| `src/reportify/modules/reports/renderer.py` | 重写 | `render_report()` + `chart_option()`；读取 vendored JS（缓存） |
| `src/reportify/modules/reports/service.py` | 更新 | 调用新渲染器；`RENDERER_ID` 由 renderer 暴露 |
| `src/reportify/api/routes/reports.py` | 更新 | 下载响应设置报告专属 CSP |
| `tests/unit/test_report_renderer.py` | 新增 | option 构建（四类图）、转义、单文件包含 echarts |
| `tests/integration/test_reports_api.py` | 更新 | 断言 `echarts-v1`、`echarts.init`、无占位横幅；XSS 转义 |
| `tests/integration/test_mcp_api.py` 等 | 更新 | 涉及 `placeholder-v1` 的断言 |

### 5.2 关键签名

```python
RENDERER_ID = "echarts-v1"

def chart_option(chart: dict) -> dict: ...          # ChartBlock 序列 → ECharts option
def render_report(*, report_id, title, summary, sections, lineage,
                  generated_at, template_name) -> str: ...
```

### 5.3 行为细节

- `chart_option` 按 `chart_type`：
  - `line`/`bar`：`xAxis.data` 取首个 series 的 x；每个 series 输出 `{type, name, data: [y...]}`。
  - `pie`：单个 series，`data: [{name, value}]`。
  - `scatter`：`xAxis.type='value'`，`data: [[x, y]]`。
  - 统一加 `tooltip`、`legend`（多 series）、`grid`。
- 模板：`<div class="chart" data-chart="opt-<id>">` + `<script type="application/json" id="opt-<id>">{{ option_json }}</script>`
  + 初始化脚本读取并 `echarts.init`；`chart` 下方 `<details>` 内保留数据表（降级）。
- ECharts JS 通过 `{{ echarts_js | safe }}` 内联（可信 vendored 资源）；JSON 通过 `| safe` 但先在 Python 侧 `json.dumps(ensure_ascii=False)`，避免 `</script>` 注入（替换为 `<\/script>`）。
- 下载：`FileResponse(..., headers={"Content-Security-Policy": REPORT_CSP, "Cache-Control": "no-store"})`。
- `report_ref.renderer`：`ReportRefView.renderer` 默认改为 `echarts-v1`。

### 5.4 Checklist

- [x] 1. vendored ECharts + 新模板 + renderer 重写。
- [x] 2. service/route 接线与 CSP。
- [x] 3. 单测（option/转义/单文件）与集成测试更新。
- [x] 4. 全量回归（M0–M6 不回归）。
- [x] 5. Reverse Sync：07 §9、09 §12 与 Spec。

---

## 6. 验证方式

| 项 | 命令 / 操作 | 期望 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | 通过 |
| 单测 | `pytest tests/unit/test_report_renderer.py` | option 与转义全通过 |
| 集成 | `pytest tests/integration/test_reports_api.py` | 报告含 `echarts.init`、`data-chart`、无「占位渲染」字样 |
| XSS | 标题/文本含 `<script>` | 输出中被转义，不出现可执行标签 |
| 下载 | `GET /reports/{id}/download` | 200、`text/html`、CSP 允许内联、单文件含 ECharts |
| 全量 | `uv run pytest -q` | 全绿 |

---

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 内联 1MB 导致报告变大 | 记录在口径；后续可改为外链 + 缓存 |
| JSON 注入 `</script>` | 序列化后替换 `</` 为 `<\/`；模板变量仅传可信串 |
| CSP 放宽影响管理台 | 仅对 `/reports/{id}/download` 响应设置专属 CSP |
| ECharts 版本升级 | 固定 5.5.0 并保留许可头；升级需跑渲染测试 |
| 无 JS 环境看不到图 | 图表下方保留数据表 |

---

## 8. Execute Log

| # | 动作 | 结果 |
| --- | --- | --- |
| 1 | 依赖 | 从 unpkg 直连获取 `echarts@5.5.0`（1,029,203 字节，Apache-2.0 头完整），vendored 到 `static/vendor/` |
| 2 | 渲染器 | `renderer.py` 重写：`chart_option()` 四类图 + `render_report()` + `script_json()`（`</` → `<\/`） |
| 3 | 模板 | `report.html.j2`：四类 block、KPI 网格、图表 + 降级表格、lineage 区块、内联 ECharts 与初始化脚本 |
| 4 | 接线 | `ReportService` 调用新渲染器；`RENDERER_ID=echarts-v1`；报告事件与工具摘要同步更新 |
| 5 | CSP | 下载响应用报告专属 CSP（允许内联），管理台严格 CSP 不变 |
| 6 | 下线 | 删除 `report_placeholder.html.j2` 与占位横幅 |
| 7 | 测试 | 14 个渲染器单测 + 更新报告集成断言；全量 318 passed |
| 8 | 回写 | 本节、07 §9、09 §12 |

## 9. Verification Evidence

| 项 | 命令 / 操作 | 结果 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | `All checks passed!` |
| 全量测试 | `REPORTIFY_TEST_DATABASE_URL=… uv run pytest -q` | `318 passed, 1 skipped in 88.90s` |
| 渲染单测 | `pytest tests/unit/test_report_renderer.py` | 14 passed |
| 集成 | `pytest tests/integration/test_reports_api.py` | 5 passed |
| 产物 | 直接渲染一份含 4 类 block 的报告 | 1,033,262 字节；含 `echarts-v1`、`echarts.init`、`data-chart`、`"type": "bar"`、lineage；**0** 处「占位渲染」 |
| 四类图 | 单测参数化 line/bar/pie/scatter | 每类均生成对应 `type` 的 option |
| XSS | 标题/摘要/文本含 `<script>`、`<img onerror>`、`<iframe>` | 全部被转义为实体，输出无可执行标签 |
| JSON 注入 | 文本含 `</script>` | 序列化为 `<\/script>`，不破坏脚本块 |
| 下载 CSP | `GET /reports/{id}/download` | 含 `script-src 'unsafe-inline'`，管理台页面仍为严格策略 |
| 降级 | 图表下方 `<details>` | 保留可读的数据表 |

## 10. Plan-Execution Diff

| 项 | 计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| ECharts 获取 | 计划 vendored | 从 unpkg 直连下载（jsdelivr 不可达） | 本机代理不通；unpkg 可直连 |
| 内联方式 | 计划内联 | 同：`<script>{{ echarts_js | safe }}</script>` | 单文件可离线打开 |
| 报告体积 | 未定 | 约 1.03 MB/份 | ECharts 内联的必然代价，已在 07 §9 注明 |
| CSP | 计划专属策略 | 同，仅下载响应覆盖 | 管理台不影响 |
| 图表降级 | 计划 `details` 表格 | 同 | 无脚本环境仍可读数据 |
| 旧模板 | 计划保留 | 删除 | 避免两套渲染路径并存 |

## 11. Review Verdict

| 轴 | 检查项 | 结论 | 证据 |
| --- | --- | --- | --- |
| Axis-1 | 目标与验收标准明确 | PASS | §1 |
| Axis-1 | 验收项逐条验证 | PASS | §9（8 条验收对应 11 项证据） |
| Axis-2 | Checklist 1–5 完成 | PASS | §5.4 |
| Axis-2 | 偏差已记录 | PASS | §10（6 项） |
| Axis-3 | 安全 | PASS | 全量转义、`</` 中和、报告专属 CSP、无外链依赖 |
| Axis-3 | 正确性 | PASS | 318 项测试；真实渲染产物核对 |
| Axis-3 | 可维护性 | PASS | option 构建与模板分离，四类图参数化测试 |
| Axis-3 | 未覆盖项 | PARTIAL | 无浏览器端 E2E（未验证图形像素）、无主题系统、报告体积偏大 |

**Overall Verdict：PASS（附后续项）**。报告链路（Schema → 渲染 → 下载）达到最终形态。

## 12. Gate

- 当前 `Review`，等待用户验收。
- 剩余 §12+：Scheduler/ARQ、Memory、Report Revision（版本树）、OAuth 2.1、审批超时。
