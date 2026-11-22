# 09 · 工程方案

> 依赖：`01-system-overview.md`、`08-data-model.md`。  
> 目标：单机、本地优先、Docker 可部署；不为未来规模预付复杂度。

---

## 1. Purpose

定义代码如何组织、依赖如何锁定、配置如何注入、测试如何证明正确、部署如何复现。本文是实现的工程契约，不包含业务代码。

---

## 2. Non-Goals

- 不做微服务、Kubernetes、服务网格。
- 不做多环境 CI/CD 平台工程；只要求本地与 Docker 可复现。
- 不引入前端构建链。
- 不承诺高可用与水平扩展。

---

## 3. 仓库结构

```text
Reportify/
├── pyproject.toml
├── uv.lock
├── alembic.ini
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── docs/
│   ├── architecture/
│   └── reportify-design-demos/
├── mydocs/
│   ├── specs/
│   └── codemap/
├── src/reportify/
│   ├── main.py
│   ├── api/
│   │   ├── app.py
│   │   ├── deps.py
│   │   ├── sse.py
│   │   └── routes/
│   │       ├── conversations.py
│   │       ├── tasks.py
│   │       ├── runs.py
│   │       ├── data_sources.py
│   │       ├── mcp.py
│   │       ├── workspace.py
│   │       ├── reports.py
│   │       └── system.py
│   ├── core/
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── security.py
│   │   ├── logging.py
│   │   ├── errors.py
│   │   └── events.py
│   ├── modules/
│   │   ├── runtime/
│   │   ├── tools/
│   │   ├── mcp/
│   │   ├── connectors/
│   │   ├── workspace/
│   │   ├── skills/
│   │   ├── conversation/
│   │   ├── reports/          # 最小契约
│   │   └── profiles/         # 最小契约
│   ├── db/
│   │   ├── models/
│   │   ├── repositories/
│   │   └── migrations/
│   ├── workers/
│   │   ├── arq_settings.py
│   │   └── jobs.py
│   ├── templates/
│   └── static/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── examples/
    └── workspace/            # 示例配置；运行时 workspace 挂载点不进 git
```

**模块公开面**：每个模块只暴露 `service.py` / `schemas.py` / `__init__.py` 中的公共类型；其他文件视为内部实现。

---

## 4. 依赖与工具链

| 类别 | 选择 | 说明 |
| --- | --- | --- |
| Python | 3.12+ | PydanticAI 要求 ≥3.11 |
| 包管理 | uv | `uv sync --frozen` |
| Web | FastAPI + Uvicorn | 异步 |
| ORM | SQLAlchemy 2.0 async | + asyncpg |
| 迁移 | Alembic | async 模板 |
| 校验 | Pydantic v2 + pydantic-settings | |
| Agent | `pydantic-ai-slim[openai,mcp]>=2.71,<3` | V2 API |
| MCP | 随 PydanticAI 安装的 FastMCP client | 不额外引入官方 SDK |
| 数据 | pandas | ≤100 万行 |
| 模板 | Jinja2 | 自动转义 |
| 队列 | ARQ + redis | 定时/长任务 |
| 加密 | cryptography | AES-GCM |
| HTTP | httpx2 | 与 MCP/FastMCP 栈一致 |
| 可观测 | OpenTelemetry SDK（可选 OTLP） | Logfire 可选，不作为依赖 |
| 测试 | pytest + pytest-asyncio | |
| 质量 | ruff + mypy（可选） | CI 阻塞 ruff/pytest |

**版本策略**：

- 应用依赖使用兼容范围 + `uv.lock` 锁定。
- PydanticAI 固定 `>=2.71,<3`；升级需要跑契约测试。
- 不在代码中硬编码模型名；通过配置注入。

---

## 5. 配置

```python
class Settings(BaseSettings):
    app_env: Literal["dev", "test", "prod"] = "dev"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    database_url: str
    redis_url: str
    workspace_dir: Path
    reports_dir: Path

    secret_key: SecretStr
    key_version: int = 1

    deepseek_api_key: SecretStr
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"

    run_timeout_seconds: int = 900
    run_request_limit: int = 40
    run_tool_calls_limit: int = 25
    run_total_tokens_limit: int = 300_000
    max_concurrent_runs: int = 4

    auth_token: SecretStr | None = None
    otel_exporter_otlp_endpoint: str | None = None
```

规则：

- `.env` 不提交；`.env.example` 只含占位符。
- `secret_key` 缺失时启动失败；生产环境禁止默认值。
- 配置只从环境/文件读取，不从数据库读取密钥。
- 所有超时、限制、模型名可配置，代码中只保留安全下限。

---

## 6. 数据库与迁移

- 异步引擎与 Session：请求级 Session；Run 使用独立 Session，避免长事务。
- Alembic 迁移放在 `src/reportify/db/migrations`；启动不自动迁移，部署显式执行。
- 命名约定：`ix_`、`uq_`、`fk_`、`ck_` 前缀。
- 内置工具在启动时幂等 upsert 到 `tool_definition`。
- 清理任务（事件/审计/快照）由 ARQ 定时执行；MVP 可先提供手动命令。
- 备份：PostgreSQL 逻辑备份 + `workspace/` 与 `reports/` 目录。

---

## 7. 模块实现规则

1. `api` 只做参数校验、鉴权、调用服务、序列化。
2. 领域服务不依赖 FastAPI 类型（`Request`、`HTTPException`）。
3. 跨模块调用通过 Protocol；禁止导入其他模块的 `internal` 文件。
4. 所有外部 I/O（PG、Redis、HTTP、MCP）都经过适配器，便于替换与测试。
5. 禁止 `eval` / `exec` / 动态 import 用户内容；禁止 shell 拼接。
6. 时间统一 UTC；ID 应用层生成。
7. 日志只写结构化字段，不拼接敏感信息。

---

## 8. 测试策略

| 层 | 范围 | 工具 |
| --- | --- | --- |
| 单元 | Query Builder、SSRF、授权判定、状态机、上下文裁剪、模板校验 | pytest |
| 集成 | PostgreSQL 迁移与仓库、Connector 只读、ARQ 任务 | pytest + 测试容器/Compose |
| 契约 | API 错误模型、SSE 事件 schema、Report Schema | pytest + JSON Schema |
| Agent | 用测试模型或 Fake Model 驱动工具循环，不调用真实 DeepSeek | PydanticAI 测试能力（以实际版本 API 为准） |
| MCP | 本地 Fake MCP Server：发现、调用、超时、错误语义 | FastMCP 测试 Server |
| 端到端（可选） | 创建会话 → 运行 → 事件 → 报告引用 | Compose + Playwright（可选，不阻塞 MVP） |

要求：

- CI 默认不访问外网、不调用真实 LLM。
- 安全相关模块（SSRF、授权、查询构造、脱敏）必须有负面用例。
- 迁移必须有升级测试；禁止只改模型不写迁移。
- 覆盖率目标：核心安全与 Runtime ≥70%，整体不设硬指标。

---

## 9. Docker 与部署

```text
docker compose services:
  api       -> uvicorn reportify.main:app
  worker    -> arq reportify.workers.arq_settings.WorkerSettings
  postgres  -> postgres:16
  redis     -> redis:7
volumes:
  reportify_pg
  reportify_redis
  ./workspace:/app/workspace
  ./reports:/app/reports
```

要求：

- 多阶段构建，运行镜像非 root。
- `uv sync --frozen --no-dev`；依赖可复现。
- 健康检查：`/health`、`/ready`；Compose 依赖 `condition: service_healthy`。
- 默认只映射 `127.0.0.1:8000`；对外暴露需显式修改。
- 不在镜像内放置 `.env` 与凭证。

---

## 10. 可观测性

| 项 | 实现 |
| --- | --- |
| 日志 | JSON；字段 `timestamp`、`level`、`request_id`、`run_id`、`task_id`、`event`、`error_code` |
| Trace | OTel：`run`、`model_request`、`tool_call`、`connector_query` |
| 指标（可选） | run 数/时长、工具失败率、MCP 连接失败、查询超时 |
| 导出 | OTLP；未配置时 no-op |
| 隐私 | 不记录 Prompt 全文、工具参数原文、凭证、样本数据 |

Langfuse 通过 OTLP 接入属于可选验证项，不作为默认依赖。

---

## 11. 安全工程

| 项 | 措施 |
| --- | --- |
| 依赖 | `uv.lock` 锁定；定期升级；禁止未审计的传递依赖 |
| 密钥 | 环境变量 + `secret` 表加密；轮换支持 `key_version` |
| 注入 | 参数化查询、标识符 allowlist、禁止拼接 |
| XSS | Jinja2 自动转义；前端使用 `textContent` |
| CSRF | SameSite + token（Cookie 模式） |
| SSRF | 统一 URL 校验器；覆盖 MCP 与 OAuth 发现链路 |
| 路径 | 所有文件访问限制在 `workspace_dir` / `reports_dir` 根目录内 |
| 进程 | 不执行用户脚本；不启用 stdio；无 shell |
| 绑定 | 默认 `127.0.0.1`；对外必须显式配置 |

---

## 12. MVP 里程碑

| 里程碑 | 内容 | 验收 |
| --- | --- | --- |
| M0 骨架 | 配置、DB、迁移、健康检查、Workspace Loader、日志 | `uv run uvicorn` 可启动；迁移通过 |
| M1 数据层 | PostgreSQL Connector、元数据同步、Query Builder、Profiling 契约 | 只读查询、超时、行数限制、lineage 通过测试 |
| M2 Agent 主链路 | Runtime、Conversation/Task、SSE、内置工具、报告引用（占位渲染） | 一次完整 run 有事件、消息、审计、报告引用 |
| M3 MCP | Hub、发现、授权、审计、Toolset 集成 | Fake Server 上完成发现/调用/拒绝/超时 |
| M4 配置与交付 | Skills/Templates、8 个视图、Docker Compose、OTel | 本地一键启动；配置变更生效；文档与实现一致 |

**进度（2026-11-22）**：M0–M5 全部实现并通过验收证据（273 项测试 + 真实进程），
见 `mydocs/specs/` 下各里程碑 Spec。M5 补齐了 07 契约的最后三处：工具审批（`waiting_approval` 同 run 续跑）、
Workspace 文件 API 与 `workspace_audit` 落库、`GET /config`。
未做（明确属于 §12+）：ARQ worker 与定时任务配置、报告正式渲染器、OAuth 2.1、审批超时自动取消。
`docker-compose.yml` 含 api/postgres/redis 三个服务，未包含 worker。

每个里程碑结束必须更新 Spec 与本文档，记录偏差。

---

## 13. 开发流程

```bash
uv sync
cp .env.example .env
docker compose up -d postgres redis
uv run alembic upgrade head
uv run uvicorn reportify.main:app --reload
uv run arq reportify.workers.arq_settings.WorkerSettings
uv run pytest
uv run ruff check .
```

约定：

- 先 Spec 后实现；实现偏差回写 Spec。
- 新模块先定义 Protocol 与数据契约，再写实现。
- 修改 `08-data-model.md` 必须同时提供迁移与仓库测试。
- 不提交 `.env`、凭证、生成报告与本地数据库文件。

---

## 14. Open Questions

1. `asyncpg` 与 `psycopg 3` 的最终选择（影响取消与超时语义）。
2. 测试容器在 Windows 本地开发环境的可用性；是否统一走 Compose。
3. 报告渲染器由 §12+ 实现期间，M2 的占位产物如何标记为「非最终」。
4. 是否需要为 `workspace/` 提供 `examples/` 初始化命令。
