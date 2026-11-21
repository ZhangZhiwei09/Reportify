# Reportify M0 · Bootstrap — Spec

> 层级：Feature Spec（实现阶段）
> 依据：`docs/architecture/09-engineering.md` §12 M0；`docs/architecture/08-data-model.md` 约定。
> 前置任务：`2026-11-21_17-32_Reportify-Architecture-V3.md`（已验收关闭）。

---

## 0. 状态

| 字段 | 值 |
| --- | --- |
| Phase | `Closed` |
| Status | `LOCKED` |
| Approval | `Plan Approved` + `全部` → 验收通过（2026-11-21） |
| 任务单元 | 可启动的工程骨架：配置、日志、DB、Alembic、健康检查、Workspace Loader |
| 不包含 | PydanticAI、Connector、MCP、Runtime、管理台页面、报告渲染 |

---

## 1. 最终目标与验收

**目标**：建立一个可本地启动、可迁移、可测试的模块化单体骨架，为 M1 数据层与 M2 Agent 主链路提供稳定地基。

**验收标准（可验证）**：

1. `uv sync` 成功，依赖锁定。
2. `uv run ruff check .` 无错误。
3. `uv run pytest` 通过；无数据库时集成测试自动 skip。
4. `uv run alembic upgrade head` 创建 `alembic_version` 与 `workspace_audit`。
5. `uv run uvicorn reportify.main:app` 启动，`GET /api/v1/health` 返回 200。
6. `WorkspaceLoader` 能加载示例 workspace；拒绝路径穿越、超大文件、非法 Skill。
7. 无任何业务分析代码、无 LLM 调用、无 MCP 连接。

---

## 2. In / Out of Scope

### In Scope

- `pyproject.toml`、uv 依赖、ruff/pytest 配置。
- `Settings`（pydantic-settings）与 `.env.example`。
- JSON 结构化日志。
- SQLAlchemy 2.0 async 引擎、Session 工厂、命名约定。
- Alembic 异步迁移环境与首个迁移（`workspace_audit`）。
- FastAPI 应用工厂、lifespan、`/api/v1/health`、`/api/v1/ready`。
- Workspace Loader：SOUL/USER/AGENTS、Skills 索引、Templates 索引、校验与 hash。
- `docker-compose.dev.yml`：PostgreSQL + Redis。
- `examples/workspace/` 示例配置。
- 单元测试与可选集成测试。

### Out of Scope

- 除 `workspace_audit` 外的数据表（M1/M2 逐步迁移）。
- Redis 客户端与 ARQ（M2/M3）。
- PydanticAI、DeepSeek、MCP、Connector、Runtime。
- 管理台页面、静态资源、Jinja2 报告。
- Docker 应用镜像与完整 Compose（M4）。

---

## 3. Research Findings

| 事实 | 结论 | 影响 |
| --- | --- | --- |
| 仓库现状 | 只有 `docs/`、`mydocs/`、`prompt.md`、`AGENTS.md`、`CLAUDE.md`；无 `pyproject.toml`、无 `src/` | 从零搭建，无需兼容旧代码 |
| 架构基线 | Python 3.12、FastAPI、SQLAlchemy 2 async、Alembic、Pydantic v2、uv | 直接按基线落地 |
| 数据模型 | `workspace_audit` 字段已定义（08 §6.19） | M0 只建这一张表，验证迁移链路 |
| Workspace 规范 | 文件大小上限、Skill frontmatter、Template YAML（06） | Loader 必须实现校验与告警 |
| 健康检查 | `/health` 存活、`/ready` 依赖就绪（07） | `ready` 检查 DB；Redis 未接入前不检查 |
| 测试环境 | 需要 PostgreSQL；Windows 本地可能无 DB | 集成测试按环境变量 skip |
| 驱动选择 | 架构文档保留 asyncpg / psycopg 3 的 Open Question | M0 先选 **asyncpg**，M1 复验 |

---

## 4. Open Questions

| # | 问题 | 默认决策 | 影响 |
| --- | --- | --- | --- |
| Q1 | 数据库驱动 | `asyncpg` | Alembic 异步 env 需额外处理 |
| Q2 | 是否在 M0 提供 dev Compose | 提供 PG + Redis | 本地可复现；不构建应用镜像 |
| Q3 | 是否一次建完所有表 | 否，只建 `workspace_audit` | 迁移增量、降低返工 |
| Q4 | `secret_key` 在 dev 的默认值 | `.env.example` 提供占位；代码无默认 | 避免生产误用 |
| Q5 | Python 3.12 还是 3.13 | 3.12 | 与基线一致 |
| Q6 | 是否在 M0 接入 OTel | 否，仅日志 | 降低复杂度；M4 接入 |

---

## 5. Plan（Contract）

### 5.1 File Changes

| 路径 | 动作 | 内容 |
| --- | --- | --- |
| `pyproject.toml` | 新增 | 项目元数据、依赖、ruff、pytest |
| `uv.lock` | 生成 | `uv sync` 产物 |
| `.gitignore` | 新增 | `.env`、`.venv`、`__pycache__`、`reports/`、`workspace/` |
| `.env.example` | 新增 | 数据库、Redis、workspace、secret 占位 |
| `docker-compose.dev.yml` | 新增 | PostgreSQL 16 + Redis 7 |
| `alembic.ini` | 新增 | script_location 指向 `src/reportify/db/migrations` |
| `README.md` | 更新 | 本地启动步骤 |
| `src/reportify/__init__.py` | 新增 | `__version__` |
| `src/reportify/main.py` | 新增 | `app = create_app()` |
| `src/reportify/api/app.py` | 新增 | 应用工厂、lifespan、路由注册 |
| `src/reportify/api/deps.py` | 新增 | `get_settings`、`get_engine` 依赖 |
| `src/reportify/api/routes/system.py` | 新增 | `/health`、`/ready` |
| `src/reportify/core/config.py` | 新增 | `Settings` |
| `src/reportify/core/logging.py` | 新增 | JSON formatter、`configure_logging` |
| `src/reportify/core/db.py` | 新增 | 引擎、Session 工厂、`check_database` |
| `src/reportify/db/models/base.py` | 新增 | `Base`、命名约定、时间戳 mixin |
| `src/reportify/db/models/workspace_audit.py` | 新增 | 映射 08 §6.19 |
| `src/reportify/db/models/__init__.py` | 新增 | 导出模型 |
| `src/reportify/db/migrations/env.py` | 新增 | Alembic async 环境 |
| `src/reportify/db/migrations/script.py.mako` | 新增 | 迁移模板 |
| `src/reportify/db/migrations/versions/0001_workspace_audit.py` | 新增 | 建表迁移 |
| `src/reportify/modules/workspace/schemas.py` | 新增 | `SkillMeta`、`TemplateMeta`、`WorkspaceSnapshot` |
| `src/reportify/modules/workspace/loader.py` | 新增 | 加载、校验、hash |
| `examples/workspace/SOUL.md` | 新增 | 示例人格 |
| `examples/workspace/USER.md` | 新增 | 示例偏好 |
| `examples/workspace/AGENTS.md` | 新增 | 示例执行规范 |
| `examples/workspace/skills/example/SKILL.md` | 新增 | 最小 Skill |
| `examples/workspace/report-templates/default.yaml` | 新增 | 最小模板 |
| `tests/conftest.py` | 新增 | 环境变量与临时 workspace fixture |
| `tests/unit/test_config.py` | 新增 | 配置解析与缺失必填项 |
| `tests/unit/test_workspace_loader.py` | 新增 | 正常、缺失、非法、穿越、超大 |
| `tests/integration/test_health.py` | 新增 | TestClient 健康检查（无 DB 时 skip） |
| `tests/integration/test_migrations.py` | 新增 | Alembic upgrade（无 DB 时 skip） |

### 5.2 关键签名

```python
# core/config.py
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    database_url: PostgresDsn
    redis_url: RedisDsn | None = None
    workspace_dir: Path = Path("workspace")
    reports_dir: Path = Path("reports")
    secret_key: SecretStr
    key_version: int = 1
    auth_token: SecretStr | None = None

@lru_cache
def get_settings() -> Settings: ...

# core/logging.py
def configure_logging(level: str = "INFO") -> None: ...

# core/db.py
def create_engine(settings: Settings) -> AsyncEngine: ...
def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]: ...
async def check_database(engine: AsyncEngine) -> bool: ...

# db/models/base.py
class Base(DeclarativeBase):
    metadata: MetaData

class TimestampMixin:
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

# modules/workspace/schemas.py
class SkillMeta(BaseModel):
    name: str
    display_name: str
    description: str
    version: int = 1
    applies_to: list[str] = []
    path: str
    content_hash: str

class TemplateMeta(BaseModel):
    name: str
    display_name: str
    description: str
    schema_version: int = 1
    path: str
    content_hash: str

class WorkspaceSnapshot(BaseModel):
    root: Path
    soul: str | None
    user: str | None
    agents: str | None
    skills: list[SkillMeta]
    templates: list[TemplateMeta]
    warnings: list[str]
    loaded_at: datetime

# modules/workspace/loader.py
class WorkspaceLoader:
    def __init__(self, root: Path, *, max_file_bytes: int = 128 * 1024) -> None: ...
    def load(self) -> WorkspaceSnapshot: ...
    def skills_index(self) -> list[SkillMeta]: ...
    def templates_index(self) -> list[TemplateMeta]: ...

# api/app.py
def create_app(settings: Settings | None = None) -> FastAPI: ...
```

### 5.3 行为细节

**Settings**

- `database_url` 与 `secret_key` 必填；缺失时启动失败并给出明确错误。
- 环境变量前缀 `REPORTIFY_`；`.env` 仅本地使用。
- `workspace_dir` 不存在时不自动创建，启动时告警并使用空快照。

**Logging**

- JSON 每行一条；字段 `timestamp`、`level`、`logger`、`message`。
- `extra` 中的 `run_id` / `task_id` / `request_id` 原样输出。
- 不输出环境变量与凭证。

**DB**

- `pool_pre_ping=True`；`pool_size=5`；`max_overflow=5`。
- Session `expire_on_commit=False`。
- `check_database` 执行 `SELECT 1`，异常返回 False。

**Workspace Loader**

- 根目录必须存在且为目录；`resolve()` 后校验路径仍位于根目录内。
- 拒绝符号链接逃逸、隐藏文件、二进制内容。
- 文件读取上限 128 KB（SOUL/USER/AGENTS）；SKILL.md 同限；Template 同限。
- Skill：解析 YAML frontmatter；`name` 必须与目录名一致；缺少 `description` 时跳过并记录 warning。
- Template：`yaml.safe_load`；必须含 `schema_version`、`name`、`sections`；非法时跳过并记录 warning。
- 计算 `sha256` 作为 `content_hash`。
- 单个文件失败不阻断整体加载；`warnings` 汇总。

**API**

- `GET /api/v1/health`：`{"status":"ok","version":"0.1.0"}`。
- `GET /api/v1/ready`：DB `SELECT 1` 成功返回 200，否则 503。
- lifespan：配置日志 → 创建引擎 → 加载 workspace 到 `app.state` → 关闭时 `engine.dispose()`。
- 不注册任何业务路由。

**Alembic**

- `env.py` 从 `Settings` 读取 `database_url`，使用 async engine + `run_sync`。
- `target_metadata = Base.metadata`。
- 迁移 `0001` 创建 `workspace_audit`：`id`、`file_path`、`content_hash`、`action`、`actor`、`detail`、`created_at`、`updated_at`；`action` 带 CHECK。
- 不使用 autogenerate 作为唯一来源；迁移文件手写并审查。

### 5.4 Checklist

- [x] 1. 创建 `pyproject.toml`、`.gitignore`、`.env.example`；执行 `uv sync`。
- [x] 2. 实现 `core/config.py` 与配置测试。
- [x] 3. 实现 `core/logging.py`。
- [x] 4. 实现 `db/models/base.py`、`workspace_audit.py`。
- [x] 5. 配置 Alembic（`alembic.ini`、`env.py`、`script.py.mako`）与 `0001` 迁移。
- [x] 6. 实现 `modules/workspace/schemas.py`、`loader.py` 与单元测试。
- [x] 7. 实现 `api/app.py`、`routes/system.py`、`main.py`。
- [x] 8. 添加 `docker-compose.dev.yml` 与 `examples/workspace/`。
- [x] 9. 更新根 `README.md` 启动说明。
- [x] 10. 运行验证：`ruff`、`pytest`、`alembic upgrade head`、启动并请求 `/health`。
- [x] 11. 回写 Execute Log 与验证证据。

---

## 6. 验证方式（Done by Evidence）

| 项 | 命令 / 操作 | 期望 |
| --- | --- | --- |
| 依赖 | `uv sync` | 成功，生成/更新 `uv.lock` |
| 静态检查 | `uv run ruff check .` | 无错误 |
| 单元测试 | `uv run pytest tests/unit -q` | 全部通过 |
| 集成测试 | `docker compose -f docker-compose.dev.yml up -d` 后 `uv run pytest tests/integration -q` | 通过；无 DB 时 skip |
| 迁移 | `uv run alembic upgrade head` | 创建 `alembic_version`、`workspace_audit` |
| 启动 | `uv run uvicorn reportify.main:app` + `curl /api/v1/health` | 200 |
| 就绪 | `curl /api/v1/ready` | DB 可用时 200，否则 503 |
| Workspace | `pytest tests/unit/test_workspace_loader.py` | 正常/异常用例通过 |

---

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| Windows 本地无 PostgreSQL | dev Compose；集成测试 skip |
| Alembic async env 配置复杂 | 先实现最小 `env.py`，用真实迁移验证 |
| `Settings` 必填项导致测试难写 | 测试通过 `monkeypatch.setenv` 注入 |
| Workspace 校验过严导致示例加载失败 | 示例文件与测试 fixture 同步维护 |
| 过早引入业务代码 | M0 明确禁止 PydanticAI / Connector / MCP |

回滚：M0 全部为新增文件；删除新增文件即可恢复，不影响已有文档。

---

## 8. Execute Log

| # | 动作 | 结果 |
| --- | --- | --- |
| 1 | 工程配置 | `pyproject.toml`、`.gitignore`、`.env.example`、`docker-compose.dev.yml`、`alembic.ini`、`README.md` 完成 |
| 2 | 依赖安装 | `uv sync` 成功；CPython 3.12.10；39 → 40 包解析 |
| 3 | 配置与日志 | `Settings`、`JsonFormatter`、`configure_logging` 完成 |
| 4 | 数据库 | async engine、Session 工厂、`WorkspaceAudit` 模型完成 |
| 5 | 迁移 | `0001_workspace_audit` 离线 SQL 生成成功，并在 PostgreSQL 16 上实际应用 |
| 6 | Workspace | Loader 支持 SOUL/USER/AGENTS、Skill、Template、路径/大小/编码校验 |
| 7 | API | 应用工厂、lifespan、`/api/v1/health`、`/api/v1/ready` 完成 |
| 8 | 示例 | `examples/workspace/` 与 dev Compose 完成 |
| 9 | 文档 | 根 `README.md` 更新为本地启动说明 |
| 10 | 验证 | 见 §9 |
| 11 | Spec 回写 | 本节与 §10、§11 完成 |

## 9. Verification Evidence

| 项 | 命令 / 操作 | 结果 |
| --- | --- | --- |
| 依赖 | `uv sync` | 成功，生成 `uv.lock` |
| 静态检查 | `uv run ruff check .` | `All checks passed!` |
| 单元 + 集成 | `uv run pytest -q` | `10 passed, 1 skipped` |
| 跳过项 | symlink 测试 | Windows 无符号链接权限，环境原因跳过 |
| 迁移（离线） | `uv run alembic upgrade head --sql` | 生成 `workspace_audit` 建表 SQL |
| 迁移（实际） | `uv run alembic upgrade head` | PostgreSQL 16 上成功；`alembic current` = `0001 (head)` |
| 健康检查 | 启动 uvicorn 后 `curl /api/v1/health` | `200 {"status":"ok","version":"0.1.0"}` |
| 就绪（有 DB） | `curl /api/v1/ready` | `200 {"status":"ready"}` |
| 就绪（无有效 DB） | `curl /api/v1/ready` | `503 {"status":"not_ready"}` |
| 测试库 | Docker Compose PostgreSQL 16 | 使用 `127.0.0.1:55432` 验证；容器 healthy |

## 10. Plan-Execution Diff

| 项 | 计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| HTTP 测试依赖 | `httpx` | 改为 `httpx2` | Starlette TestClient 已弃用 `httpx`；`httpx2` 与后续 MCP/FastMCP 栈一致 |
| Compose 端口 | 固定 5432 / 6379 | 环境变量覆盖，默认不变 | 本机 5432 已被占用，需在 55432 验证 |
| pytest 临时目录 | 默认系统 temp | `--basetemp=.pytest-tmp` | Windows 系统 temp 目录权限导致 `tmp_path` 失败 |
| 示例文件 | 计划包含 | 已包含 SOUL/USER/AGENTS/Skill/Template | 无偏差 |

## 11. Review Verdict

| 轴 | 检查项 | 结论 | 证据 |
| --- | --- | --- | --- |
| Axis-1 | 目标与验收标准明确 | PASS | §1 |
| Axis-1 | 全部验收项已验证 | PASS | §9 |
| Axis-2 | Checklist 1–11 完成 | PASS | §5.4 全部勾选 |
| Axis-2 | 偏差已记录 | PASS | §10 |
| Axis-3 | 代码正确性 | PASS | 10 项测试通过；健康/就绪实测 |
| Axis-3 | 安全边界 | PASS | 路径穿越、超大、二进制、UTF-8 校验；必填 secret |
| Axis-3 | 可维护性 | PASS | 模块边界清晰；配置集中；无业务逻辑 |
| Axis-3 | 未覆盖项 | PARTIAL | Windows symlink 测试跳过；无 CI 配置（计划外） |

**Overall Verdict：PASS（附环境性跳过项）**。无阻塞问题；等待用户验收。

## 12. Gate

- M0 已关闭（`Closed`），用户验收通过。
- 下一阶段：M1 数据层 Spec `mydocs/specs/2026-11-21_18-06_Reportify-M1-Data-Layer.md`。
- 未批准 M1 Plan 前，不实现 Connector、元数据同步或 Profiling。

## 13. Acceptance Record

| 项 | 内容 |
| --- | --- |
| 验收人 | 用户 |
| 日期 | 2026-11-21 |
| 结论 | M0 验收通过，无修改要求 |
| 证据 | 用户消息「M0 验收通过」；实测见 §9 |
| 后续 | M1 数据层 Research / Plan |
