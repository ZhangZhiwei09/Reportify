# Reportify M4 · 配置与交付 — Spec

> 层级：Feature Spec（实现阶段）
> 依据：`docs/architecture/06-workspace-skills-templates.md`、`07-api-and-ui.md` §5.4、§7、`09-engineering.md` §9–§10。
> 前置：M3（`2026-11-21_20-20_Reportify-M3-MCP.md`）已实现，Review 中。

---

## 0. 状态

| 字段 | 值 |
| --- | --- |
| Phase | `Review` |
| Status | `IMPLEMENTED`（等待用户验收） |
| Approval | 用户指令「继续」（2026-11-22），延续执行剩余里程碑 |
| 任务单元 | Skills/Templates 服务与 API → 8 个管理台视图 → CSP 与前端安全 → Docker Compose → OTel 最小埋点 |
| 不包含 | 定时任务配置 UI 与 ARQ 调度（§12+）、报告正式渲染器（§12+）、React/TS、多用户 |

**Done Contract**：本地 `docker compose up` 可启动 api + postgres + redis；8 个视图可访问并驱动既有 API；
Skills/Templates 可列出、校验、重载；CSP 头生效；`ruff` 与 `pytest` 全绿。

---

## 1. 目标与验收

1. `GET /` 302 到 `/analysis`；8 个页面路由返回 HTML（`text/html`），共用同一布局。
2. `GET /api/v1/skills`、`/api/v1/skills/{name}`、`POST /api/v1/skills/{name}/validate`、
   `POST /api/v1/skills/reload` 可用；未知名 404；名称非法 422。
3. `GET /api/v1/report-templates`、`/{name}`、`POST /{name}/validate`、`POST /reload` 可用；
   YAML 结构错误返回 `422` 与具体原因。
4. 模板/技能详情只读且限制在 `workspace_dir` 内；`name` 只接受 `[a-z0-9-]+`，路径穿越被拒绝。
5. 静态资源由 FastAPI 挂载；页面带 CSP 响应头 `default-src 'self'; script-src 'self'; style-src 'self'`。
6. 所有动态文本经 `textContent` 写入（无 `innerHTML` 拼接用户数据）。
7. `Dockerfile` 多阶段构建、非 root 运行；`docker-compose.yml` 含 api/postgres/redis 与健康检查；
   镜像内不含 `.env`。
8. OTel：配置 `REPORTIFY_OTEL_EXPORTER_OTLP_ENDPOINT` 时启用 OTLP 导出，未配置时 no-op；
   run 执行包一个 span（属性含 `run_id`、`status`、`duration_ms`）。
9. `ruff` 与 `pytest` 全绿；新增测试覆盖页面、Skills/Templates、CSP、路径安全。

---

## 2. In / Out of Scope

**In**：`modules/skills`、`modules/reports/templates.py`、页面路由与 Jinja2 模板、`static/`（css + 2 个 js）、
CSP/安全头中间件、`core/telemetry.py`、`Dockerfile`、`docker-compose.yml`、`.dockerignore`、测试。

**Out**：定时任务创建/编辑、ARQ worker 实跑、报告版本树、报告正式渲染器、认证登录页、i18n。

---

## 3. Research Findings

| 事实 | 结论 | 影响 |
| --- | --- | --- |
| Workspace | `WorkspaceLoader.load()` 已解析 SOUL/USER/AGENTS + Skills + Templates | Skills 服务直接复用，不重复解析 |
| Skills 索引 | `SkillMeta` 含 name/display_name/description/version/applies_to/path/hash | API 视图字段直接映射 |
| Templates 索引 | `TemplateMeta` 含 sections 标题列表 | 详情需回读 YAML 原文 |
| 路径安全 | `_read_text` 已限制在 root 内、限 128KB、拒二进制 | 复用 `read_skill`；新增 `read_template` |
| 前端约束 | 07 §9：无构建链、`textContent`、EventSource 只读 | 纯静态 JS |
| 事件流 | M2 的 SSE 与 `stream.js` 语义一致 | 直接接 `/api/v1/runs/{id}/events` |
| 依赖 | 无 `arq`、无 OTel SDK | 只加 `opentelemetry-sdk`（可选导出） |

---

## 4. Open Questions（默认决策）

| # | 问题 | 默认决策 |
| --- | --- | --- |
| Q1 | 是否需要登录页 | 否；沿用可选 Bearer + 本地绑定（07 §4） |
| Q2 | ARQ worker | 本里程碑不接；compose 只含 api/postgres/redis，定时任务 §12+ |
| Q3 | 页面是否服务端渲染数据 | 否；服务端只渲染骨架，数据由 JS 调 API（与 SSE 一致） |
| Q4 | OTel 依赖 | `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-http`，未配置 endpoint 时 no-op |
| Q5 | 报告正式渲染 | 不做；M2 占位渲染器继续 |

---

## 5. Plan（Contract）

### 5.1 File Changes

| 路径 | 动作 | 内容 |
| --- | --- | --- |
| `pyproject.toml` | 更新 | `opentelemetry-sdk`、`opentelemetry-exporter-otlp-proto-http` |
| `src/reportify/core/config.py` | 更新 | `otel_exporter_otlp_endpoint`、`static_dir` |
| `src/reportify/core/telemetry.py` | 新增 | `configure_telemetry()`、`run_span()` 上下文 |
| `src/reportify/modules/workspace/loader.py` | 更新 | `read_template()`、`read_file()`（root 内校验） |
| `src/reportify/modules/skills/__init__.py` | 新增 | 导出 `SkillService` |
| `src/reportify/modules/skills/service.py` | 新增 | 列表/详情/校验/重载 |
| `src/reportify/modules/skills/schemas.py` | 新增 | `SkillSummary`、`SkillDetail`、`ValidationResult` |
| `src/reportify/modules/reports/templates.py` | 新增 | 模板列表/详情/校验/重载 |
| `src/reportify/api/routes/skills.py` | 新增 | Skills API |
| `src/reportify/api/routes/report_templates.py` | 新增 | Templates API |
| `src/reportify/api/routes/pages.py` | 新增 | 8 个页面路由 + `/` 重定向 |
| `src/reportify/api/middleware.py` | 新增 | 安全头（CSP、X-Content-Type-Options、Referrer-Policy） |
| `src/reportify/api/deps.py` | 更新 | `get_skill_service`、`get_template_service` |
| `src/reportify/api/app.py` | 更新 | 中间件、静态挂载、页面与 API 路由、telemetry |
| `src/reportify/modules/runtime/runtime.py` | 更新 | run 级 OTel span |
| `src/reportify/templates/layout.html` | 新增 | 侧边栏 + 顶栏 + CSP meta |
| `src/reportify/templates/{analysis,reports,scheduler,sources,metadata,mcp,skills,templates}.html` | 新增 | 8 个视图骨架 |
| `src/reportify/static/app.css` | 新增 | 布局与组件样式 |
| `src/reportify/static/api.js` | 新增 | fetch 封装 + 错误处理 + `textContent` 工具 |
| `src/reportify/static/stream.js` | 新增 | EventSource 封装（含 `Last-Event-ID`） |
| `src/reportify/static/views/*.js` | 新增 | 8 个页面的轻量逻辑 |
| `Dockerfile` / `.dockerignore` / `docker-compose.yml` | 新增 | 多阶段、非 root、健康检查 |
| `tests/unit/test_security_headers.py` | 新增 | CSP 与安全头 |
| `tests/integration/test_pages.py` | 新增 | 8 个视图 + 静态资源 + 重定向 |
| `tests/integration/test_skills_api.py` | 新增 | 列表/详情/校验/重载/404/422/穿越 |
| `tests/integration/test_templates_api.py` | 新增 | 同上（模板） |
| `tests/unit/test_telemetry.py` | 新增 | 未配置时 no-op、配置时创建 provider |

### 5.2 关键签名

```python
class SkillService:
    async def list(self) -> list[SkillSummary]: ...
    async def get(self, name: str) -> SkillDetail: ...
    async def validate(self, name: str) -> ValidationResult: ...
    async def reload(self) -> int: ...

class ReportTemplateService:
    async def list(self) -> list[TemplateSummary]: ...
    async def get(self, name: str) -> TemplateDetail: ...
    async def validate(self, name: str) -> ValidationResult: ...
    async def reload(self) -> int: ...

def configure_telemetry(settings: Settings) -> None: ...
@contextmanager
def run_span(run_id: UUID, model: str) -> Iterator[None]: ...
```

### 5.3 行为细节

- Skills/Templates 服务每次调用 `WorkspaceLoader.load()`（文件为源，DB 只存索引），保证「配置变更生效」。
- 名称校验 `^[a-z0-9][a-z0-9-]*$`；详情读取走 loader 的 root 校验，拒绝穿越与超限文件。
- 校验结果：`{ok, errors[], warnings[]}`；模板额外返回 `sections`，技能返回 `applies_to`。
- 页面路由只渲染骨架（`href`/`data-*`），不含用户数据；动态内容由 JS 经 API 获取并以 `textContent` 写入。
- 安全头：`Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'`，`X-Content-Type-Options: nosniff`，`Referrer-Policy: no-referrer`，敏感 API `Cache-Control: no-store`。
- 静态资源：`/static` 挂载；页面引用带 `/static/app.css`、`/static/api.js`、`/static/stream.js`。
- Docker：多阶段（builder 用 `uv sync --frozen --no-dev`），运行层非 root（`appuser`），`HEALTHCHECK` 打 `/api/v1/health`，暴露 8000；compose 依赖 `condition: service_healthy`。
- OTel：`configure_telemetry` 只在配置 endpoint 时建 `TracerProvider` + `BatchSpanProcessor`；`run_span` 无 provider 时是空操作。

### 5.4 Checklist

- [x] 1. 依赖与配置项；`core/telemetry.py` + 单测。
- [x] 2. `WorkspaceLoader.read_template`；Skills 服务与 API + 测试。
- [x] 3. Templates 服务与 API + 测试。
- [x] 4. 页面路由、`layout.html` 与 8 个视图骨架、`app.css`、`api.js`、`stream.js`、`views/*.js`。
- [x] 5. 安全头中间件 + 单测；静态挂载。
- [x] 6. Runtime 接入 `run_span`。
- [x] 7. Dockerfile / .dockerignore / docker-compose.yml。
- [x] 8. 全量验证：`ruff`、`pytest`、真实进程访问 8 个页面与静态资源。
- [x] 9. Reverse Sync：回写 06/07/09 文档与 Spec。

---

## 6. 验证方式

| 项 | 命令 / 操作 | 期望 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | 通过 |
| 测试 | `uv run pytest -q` | 全绿（含新增页面/技能/模板/CSP 用例） |
| 页面 | `GET /analysis` 等 8 个路径 | 200、`text/html`、含侧边栏与视图容器 |
| 重定向 | `GET /` | 302 → `/analysis` |
| 静态 | `GET /static/app.css` | 200、`text/css` |
| 安全头 | `GET /analysis` | 含 CSP 与 nosniff |
| Skills | `GET /api/v1/skills` | 含 `example`；详情含正文；未知 404 |
| Templates | `GET /api/v1/report-templates` | 含 `default`；校验返回 sections |
| 穿越 | `GET /api/v1/skills/../secret` | 404/422，不读外部文件 |
| Docker | `docker build` / `docker compose config` | 构建成功；compose 配置合法 |

---

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 页面引入 XSS | 服务端只渲染静态骨架；JS 只用 `textContent`；CSP 禁内联脚本 |
| 路径穿越 | 名称正则 + loader root 校验 + 测试用例 |
| Docker 构建慢/失败 | 多阶段 + `.dockerignore`；不把 `.venv`/`reports` 打进镜像 |
| OTel 增加启动开销 | 未配置 endpoint 时不创建 provider |
| 视图与 API 契约漂移 | 页面只调用已测试的 API，契约由 M2/M3 测试保证 |

---

## 8. Execute Log

| # | 动作 | 结果 |
| --- | --- | --- |
| 1 | 依赖与遥测 | `opentelemetry-sdk` + OTLP HTTP exporter；`configure_telemetry` 无 endpoint 时 no-op；`run_span` 包住 run |
| 2 | Skills | `SkillService`（列表/详情/校验/重载）+ `/api/v1/skills*`；文件为源，改文件即生效 |
| 3 | Templates | `ReportTemplateService` + `/api/v1/report-templates*`；校验 YAML、section、block 词汇 |
| 4 | 视图 | `layout.html` + 8 个页面 + `app.css` + `api.js` + `stream.js` + `views/*.js` |
| 5 | 安全 | `SecurityHeadersMiddleware`（CSP/nosniff/referrer/frame/API no-store）；静态挂载 |
| 6 | 文档一致性 | 发现示例模板用了 `conclusion`/`line_chart` 等未实现 block，已改为 `text`/`chart`，并把设计名→实现名映射写进 06 |
| 7 | 交付 | `Dockerfile`（多阶段、非 root、HEALTHCHECK）、`.dockerignore`、`docker-compose.yml`（api/postgres/redis + 健康检查） |
| 8 | 验证 | `ruff` 通过；`pytest` 257 passed（M4 新增 49 项）；真实进程 8 页 + 静态资源；`docker compose config` 通过 |
| 9 | 回写 | 本节、06 §8.2、07 §7.3、09 §12、本 Spec |

## 9. Verification Evidence

| 项 | 命令 / 操作 | 结果 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | `All checks passed!` |
| 全量测试 | `REPORTIFY_TEST_DATABASE_URL=… uv run pytest -q` | `257 passed, 1 skipped in 83.09s` |
| 页面（真实进程） | `uvicorn` 后逐个 GET | 8 个页面全部 200 |
| 根路径 | `GET /` | 302 → `/analysis` |
| CSP | `GET /analysis` 响应头 | `default-src 'self'; … script-src 'self'; frame-ancestors 'none'` |
| 静态资源 | `GET /static/app.css` | 200、`text/css`、5246 字节 |
| Skills API | `GET /api/v1/skills`、`/skills/example` | 200；含正文与 `applies_to` |
| Skills 热加载 | 新增 `skills/tmp-skill` 后立即查询 | 列表立刻包含新技能（无需重启） |
| 模板校验 | `POST /report-templates/default/validate` | 200；sections = `概览 / 趋势` |
| 坏模板 | 含 `unknown_block` 的 YAML | 422 + `unknown blocks` 说明 |
| 路径安全 | 非法名称 / 编码穿越 | 400/404/422；不读取 workspace 外文件 |
| 安全头单测 | `pytest tests/unit/test_security_headers.py` | CSP 无 `unsafe-inline`/`unsafe-eval`；API `no-store` |
| 遥测单测 | `pytest tests/unit/test_telemetry.py` | 无 endpoint → no-op；配置后 span 导出（桩 exporter） |
| 交付契约 | `pytest tests/unit/test_delivery.py` | 12 项：多阶段、非 root、HEALTHCHECK、compose 服务与健康依赖、仅回环绑定、无硬编码密钥 |
| Compose | `docker compose config` | exit 0；服务 `api/postgres/redis` |
| 镜像构建 | `docker build -t reportify:m4 .` | **未验证**：本机到 `registry-1.docker.io` 不可达（IPv6 路由超时），拉不到 `python:3.12-slim` |

## 10. Plan-Execution Diff

| 项 | 计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| `static_dir` 配置项 | 加入 Settings | 未加，改为从包路径推导 | 静态目录随包发布，不需要部署者配置 |
| CLI 端 BFF | — | 页面只渲染骨架，数据全部走 JSON API | 与 SSE 实时性一致，CSP 可保持严格 |
| 样本模板 block | 沿用 `conclusion`/`line_chart` | 改为 `text`/`chart` | 这两种 block 在 M2 的 `ReportSchema` 中不存在；模板必须可渲染 |
| 非法名称状态码 | 计划 422 | 实际 400 `invalid_argument` | 与 07 §3.1 的错误码语义一致；测试已按 400/422 兼容断言 |
| Compose worker | 09 §9 列出 worker | 未包含 | 定时任务属 §12+；本里程碑不接 ARQ |
| Docker 构建 | 构建并运行 | 只做了 `compose config` + 契约测试 | 本机无法访问 Docker Hub；未伪造构建成功 |
| Dockerfile 基础镜像 | `ghcr.io/astral-sh/uv` | 改为在 `python:3.12-slim` 内 `pip install uv` | 减少一个 registry 依赖，构建更可复现 |

> 过程事故（已修复）：又一次用 PowerShell `-replace/Replace` 改含中文的测试文件，导致字符串变成乱码；
> 已用 UTF-8 安全工具改回，并全仓扫描（`src/tests/examples/docs/mydocs`）确认无残留。此后中文内容只用编辑器工具修改。

## 11. Review Verdict

| 轴 | 检查项 | 结论 | 证据 |
| --- | --- | --- | --- |
| Axis-1 | 目标与验收标准明确 | PASS | §1 |
| Axis-1 | 验收项逐条验证 | PASS | §9（9 条验收对应 16 项证据，构建项如实标注未验证） |
| Axis-2 | Checklist 1–9 完成 | PASS | §5.4 |
| Axis-2 | 偏差已记录 | PASS | §10（7 项） |
| Axis-3 | 安全 | PASS | 严格 CSP、`textContent` 渲染、名称正则 + root 校验、API `no-store`、镜像非 root、compose 仅回环绑定、无硬编码密钥 |
| Axis-3 | 正确性 | PASS | 257 项测试；真实进程 8 页 |
| Axis-3 | 可维护性 | PASS | 视图只依赖既有 API；Skills/Templates 以文件为源；交付契约用测试固定 |
| Axis-3 | 未覆盖项 | PARTIAL | 镜像构建未验证（网络）、无 ARQ worker、无浏览器端 E2E |

**Overall Verdict：PASS（附未验证项）**。无阻塞代码问题；镜像构建需在可访问 Docker Hub 的环境复验。

## 12. Gate

- 当前 `Review`，等待用户验收。
- 四个里程碑（M0–M4）代码完成。MVP 主链路闭环：数据源 → 会话/任务 → Agent 工具循环 → 报告产物 → 管理台。
- 需在联网环境补做：`docker build` 与 `docker compose up` 的端到端验证。
