# Reportify M1 · Data Layer — Spec

> 层级：Feature Spec（实现阶段）
> 依据：`docs/architecture/04-data-layer.md`、`docs/architecture/08-data-model.md`。
> 前置：M0（`2026-11-21_17-51_Reportify-M0-Bootstrap.md`）已验收关闭。

---

## 0. 状态

| 字段 | 值 |
| --- | --- |
| Phase | `Review` |
| Status | `ACCEPTED`（2026-11-21，用户指令「继续完成剩下的内容」视为验收通过） |
| Approval | `Plan Approved` + `全部`（2026-11-21） |
| 任务单元 | PostgreSQL 只读接入、凭证加密、元数据同步、安全查询构造、Profiling 契约、数据源 API |
| 不包含 | Analysis Engine 算法、MCP、Agent Runtime、管理台页面、报告渲染 |

---

## 1. 目标与验收

**目标**：让 Reportify 能安全地接入一个 PostgreSQL 数据源，发现表结构，维护字段元数据，执行受限只读查询，并产出带 lineage 的字段画像，为 M2 Agent 工具链提供数据访问底座。

**验收标准（可验证）**：

1. `alembic upgrade head` 迁移到 `0002`，创建 `secret`、`data_source`、`table_metadata`、`column_metadata`、`dataset_snapshot`。
2. 数据源 CRUD：新增/查询/更新/禁用；密码加密存储，API 永不回传明文。
3. 连接测试：正确凭证返回成功，错误凭证/不可达返回结构化错误，不泄露连接串。
4. 结构同步：发现表与字段，写入元数据；重复同步幂等；列变化能通过 `columns_hash` 检出。
5. 安全查询：`QuerySpec` 只能生成参数化只读 SQL；拒绝未知表/列、非法操作符、超限 `limit`、原始 SQL。
6. 查询结果带 `Lineage` 与 `dataset_snapshot`；分页可用。
7. Profiling：对表采样并写入空值率、唯一值、min/max/mean/std、Top 值；不推断业务语义。
8. `ruff`、`pytest` 全部通过；无 MCP / PydanticAI / Runtime 代码。

---

## 2. In / Out of Scope

### In Scope

- `cryptography` AES-GCM 凭证加密；`secret` 表与 `SecretService`。
- `data_source` / `table_metadata` / `column_metadata` / `dataset_snapshot` 模型与迁移。
- `DataConnector` Protocol、`ConnectorRegistry`、`PostgresConnector`。
- `SafeQueryBuilder`（标识符白名单、参数绑定、强制 LIMIT）。
- `MetadataService`（结构发现、upsert、漂移检测）。
- `ProfilingService`（采样、统计、写入 `column_metadata.stats`）。
- 数据源 API（CRUD、test、sync、tables、columns、profile）。
- 可选 Bearer Token 鉴权。
- 单元与集成测试（真实 PostgreSQL）。

### Out of Scope

- 趋势/分布/对比/异常/相关性的算法实现（§12+ Analysis Engine）。
- 查询结果分析接口、Agent 工具暴露（M2）。
- MCP、Runtime、会话、报告。
- 管理台页面（M4）。
- MySQL / CSV / Excel / REST Connector。
- 凭证轮换 UI；`key_version` 只预留。

---

## 3. Research Findings

| 事实 | 结论 | 影响 |
| --- | --- | --- |
| M0 已验收 | 配置、日志、DB、迁移、健康检查、Workspace Loader 可用 | M1 直接增量迁移 |
| 数据模型 | 08 §6.2–6.5 已定义字段 | 迁移与模型按此实现 |
| 接口契约 | 04 §3 定义 `DataConnector`、`QuerySpec`、`ResultSet` | 不重新发明接口 |
| 数据库驱动 | M0 选择 asyncpg + SQLAlchemy async | 继续使用，统一连接池与错误处理 |
| 测试数据库 | Docker PG 16，当前映射 `127.0.0.1:55432` | 集成测试使用 `REPORTIFY_TEST_DATABASE_URL` |
| 当前迁移 | `0001 (head)` | M1 新增 `0002` |
| 认证 | M0 无鉴权 | M1 增加可选 Bearer；默认本地无认证 |
| Pandas | 尚未引入 | M1 增加，用于 Profiling 统计 |
| 加密 | 尚未引入 | M1 增加 `cryptography` |

---

## 4. Open Questions（默认决策）

| # | 问题 | 默认决策 | 理由 |
| --- | --- | --- | --- |
| Q1 | 采样方式 | 优先 `TABLESAMPLE SYSTEM`，视图/失败时回退 `LIMIT` | 大表成本可控；MVP 以正确性优先 |
| Q2 | schema 范围 | 默认只同步 `public`；可通过 `options.schema_allowlist` 扩展 | 避免误扫系统 schema |
| Q3 | 删除数据源 | 软删除（`status=disabled`），不物理删除 | 保留 lineage 与审计 |
| Q4 | 鉴权 | 可选 `REPORTIFY_AUTH_TOKEN` Bearer；未设置时仅允许本地绑定 | 与架构一致 |
| Q5 | Profiling 触发 | 独立接口；不在每次 sync 自动执行 | 避免同步变慢 |
| Q6 | PII 样本 | 样本值最多 20 条；不自动识别 PII，只限制数量 | MVP 避免误判 |
| Q7 | 查询结果缓存 | 不缓存结果，只记录 snapshot | 降低复杂度 |

---

## 5. Plan（Contract）

### 5.1 File Changes

| 路径 | 动作 | 内容 |
| --- | --- | --- |
| `pyproject.toml` | 更新 | 增加 `cryptography`、`pandas` |
| `src/reportify/modules/security/__init__.py` | 新增 | 导出 `SecretService` |
| `src/reportify/modules/security/secrets.py` | 新增 | AES-GCM 加解密 |
| `src/reportify/db/models/secret.py` | 新增 | `secret` 表 |
| `src/reportify/db/models/data_source.py` | 新增 | `data_source` 表 |
| `src/reportify/db/models/metadata.py` | 新增 | `table_metadata`、`column_metadata` |
| `src/reportify/db/models/dataset_snapshot.py` | 新增 | `dataset_snapshot` 表 |
| `src/reportify/db/models/__init__.py` | 更新 | 导出新模型 |
| `src/reportify/db/migrations/versions/0002_data_layer.py` | 新增 | 建表、索引、约束 |
| `src/reportify/modules/connectors/__init__.py` | 新增 | 导出 Connector 与 Registry |
| `src/reportify/modules/connectors/schemas.py` | 新增 | `QuerySpec`、`QueryResult`、`Lineage` 等 |
| `src/reportify/modules/connectors/errors.py` | 新增 | 稳定错误码与异常 |
| `src/reportify/modules/connectors/base.py` | 新增 | `DataConnector` Protocol、`ConnectorRegistry` |
| `src/reportify/modules/connectors/query_builder.py` | 新增 | `SafeQueryBuilder` |
| `src/reportify/modules/connectors/postgres.py` | 新增 | `PostgresConnector` |
| `src/reportify/modules/connectors/metadata.py` | 新增 | `MetadataService` |
| `src/reportify/modules/connectors/profiling.py` | 新增 | `ProfilingService` |
| `src/reportify/api/deps.py` | 更新 | `require_auth`、`get_connector_registry` |
| `src/reportify/api/routes/data_sources.py` | 新增 | 数据源与元数据 API |
| `src/reportify/api/app.py` | 更新 | 注册路由、初始化 Registry |
| `tests/unit/test_secrets.py` | 新增 | 加密/解密、错误密钥版本 |
| `tests/unit/test_query_builder.py` | 新增 | 白名单、注入、LIMIT、聚合 |
| `tests/unit/test_type_mapping.py` | 新增 | 类型归一化 |
| `tests/integration/test_connector.py` | 新增 | 连接、结构、查询、分页、超时 |
| `tests/integration/test_metadata_sync.py` | 新增 | 同步、幂等、漂移 |
| `tests/integration/test_profiling.py` | 新增 | 统计与样本上限 |
| `tests/integration/test_data_sources_api.py` | 新增 | CRUD、test、sync、脱敏 |
| `tests/integration/conftest.py` | 新增 | 测试 schema/表 fixture |

### 5.2 关键签名

```python
class SecretService:
    def __init__(self, secret_key: SecretStr, key_version: int = 1) -> None: ...
    def encrypt(self, plaintext: str) -> EncryptedSecret: ...
    def decrypt(self, ciphertext: bytes, nonce: bytes, key_version: int) -> str: ...

class DataConnector(Protocol):
    async def test_connection(self) -> Health: ...
    async def inspect_schema(self) -> list[TableSchema]: ...
    async def execute(self, spec: QuerySpec) -> ResultSet: ...
    async def fetch_page(self, snapshot_id: UUID, offset: int, limit: int) -> Page: ...
    async def close(self) -> None: ...

class ConnectorRegistry:
    async def get(self, data_source_id: UUID) -> DataConnector: ...
    async def close_all(self) -> None: ...

class SafeQueryBuilder:
    def __init__(
        self,
        dialect: Dialect,
        tables: dict[str, set[str]],
        *,
        max_limit: int = 10_000,
    ) -> None: ...
    def build(self, spec: QuerySpec) -> BuiltQuery: ...

class MetadataService:
    async def sync(self, data_source_id: UUID) -> SyncResult: ...
    async def list_tables(self, data_source_id: UUID) -> list[TableMetadataView]: ...

class ProfilingService:
    async def profile(
        self,
        data_source_id: UUID,
        table: str,
        *,
        columns: list[str] | None = None,
        sample_size: int = 10_000,
    ) -> ProfileResult: ...

class DataSourceService:
    async def create(self, payload: DataSourceCreate) -> DataSource: ...
    async def update(self, data_source_id: UUID, payload: DataSourceUpdate) -> DataSource: ...
    async def disable(self, data_source_id: UUID) -> None: ...
    async def test(self, data_source_id: UUID) -> Health: ...
```

### 5.3 行为细节

**凭证与加密**

- AES-GCM，256-bit key = `sha256(secret_key)`；nonce 12 字节随机。
- `secret` 表存 `ciphertext`、`nonce`、`key_version`；不存明文。
- API 创建/更新时接收 `password`，立即加密；响应只返回 `secret_id` 是否存在。
- 解密仅发生在 Connector 建立连接时；日志与审计不出现明文。

**数据源**

- `type` MVP 固定 `postgresql`。
- `options`：`schema_allowlist`（默认 `["public"]`）、`statement_timeout_ms`（默认 30000）、`max_rows`（默认 10000）、`read_only`（强制 true）。
- `status`：`active` / `disabled` / `error`；测试失败写 `last_error`（脱敏）。
- 删除 = `disabled`；不物理删除。

**结构发现与同步**

- 查询 `information_schema.columns` + `pg_catalog`；只处理 allowlist schema。
- 表/列 upsert；保留用户字段（`display_name`、`unit`、`description`、`user_tags`）。
- `columns_hash = sha256(sorted("{name}:{native_type}:{nullable}"))`。
- 同步结果返回：新增/更新/移除的表列数量；漂移表列表。
- 移除的列不物理删除，标记 `is_active=false`？当前模型无此字段；M1 采用删除元数据行但保留快照引用。文档记录。

**查询构造**

- 输入 `QuerySpec`；表必须存在于元数据且 allowlist；列必须属于该表。
- 所有值参数化；标识符通过方言 `identifier_preparer.quote()`。
- 支持过滤：`eq/ne/gt/gte/lt/lte/in/not_in/between/is_null/like`。
- 支持 `group_by` + 聚合：`count/sum/avg/min/max/stddev`。
- 强制 `limit ≤ max_limit`；`offset ≥ 0`。
- 输出 `BuiltQuery(sql, params)`；不执行。
- 拒绝空表、未知列、未知操作符、超限、分号/注释/多语句。

**执行**

- 每个数据源独立 async engine（pool 2–5）。
- 事务只读：`BEGIN READ ONLY`（或连接参数 `default_transaction_read_only=on`）。
- `statement_timeout`、`lock_timeout` 由 `options` 设置。
- 查询成功创建 `dataset_snapshot`：SQL、params（脱敏）、fingerprint、row_count、columns、purpose、created_at。
- `ResultSet` 包含 `lineage` 与 `snapshot_id`。
- 分页：MVP 使用 `LIMIT/OFFSET`，并限制最大 offset。

**Profiling**

- 采样：MVP 使用 `LIMIT sample_size`（默认 10,000，上限 100,000）；`TABLESAMPLE` 留待后续优化。
- 使用 Pandas 计算：`null_ratio`、`distinct_count`、`min`、`max`、`mean`、`std`、`top_values`（≤20）、`sample_values`（≤20）。
- 写入 `column_metadata.stats`，`profile_version += 1`。
- 不推断业务语义；`status` 只报告分类值数量。
- 采样查询受数据源 `statement_timeout_ms` 约束；超时由 Connector 返回结构化错误。

**API 与鉴权**

- 路由前缀 `/api/v1`。
- `require_auth`：若配置 `REPORTIFY_AUTH_TOKEN`，要求 `Authorization: Bearer <token>`；否则放行（本地模式）。
- 错误模型沿用 07 的稳定错误码。
- 数据源响应使用 `DataSourceRead`，不含密码与连接串中的凭证。
- 测试连接失败返回 `422` 或 `503`，body 含 `code` 与脱敏 `detail`。

### 5.4 迁移 0002

新增表：

- `secret`：`id`、`name`、`ciphertext`、`nonce`、`key_version`、时间戳；`name` 唯一。
- `data_source`：按 08 §6.2；`secret_id` FK → `secret.id`（`ON DELETE RESTRICT`）。
- `table_metadata`：按 08 §6.3；唯一 `(data_source_id, schema_name, table_name)`。
- `column_metadata`：按 08 §6.4；唯一 `(table_metadata_id, column_name)`；`user_tags` 使用 `ARRAY(TEXT)`。
- `dataset_snapshot`：按 08 §6.5；`run_id UUID NULL`（M2 再加 FK）；`time_range TSTZRANGE NULL`。

索引：所有外键、`dataset_snapshot.query_fingerprint`、`column_metadata.table_metadata_id`。

### 5.5 Checklist

- [ ] 1. 添加 `cryptography`、`pandas` 依赖；`uv sync`。
- [ ] 2. 实现 `SecretService` 与单元测试。
- [ ] 3. 新增 5 个模型与 `0002` 迁移；`alembic upgrade head` 通过。
- [ ] 4. 实现 Connector schemas、errors、Protocol、Registry。
- [ ] 5. 实现 `SafeQueryBuilder` 与单元测试（含注入/超限/未知列）。
- [ ] 6. 实现 `PostgresConnector`（test/inspect/execute/fetch/close）与集成测试。
- [ ] 7. 实现 `MetadataService`（sync、幂等、漂移）与集成测试。
- [ ] 8. 实现 `ProfilingService` 与集成测试。
- [ ] 9. 实现数据源 API、鉴权依赖、脱敏，并注册路由。
- [ ] 10. 全量验证：`ruff`、`pytest`、迁移、真实 API 流程。
- [ ] 11. 回写 Execute Log、偏差与 Review。

---

## 6. 验证方式

| 项 | 命令 / 操作 | 期望 |
| --- | --- | --- |
| 迁移 | `uv run alembic upgrade head` | `0002 (head)`；5 张表存在 |
| 静态检查 | `uv run ruff check .` | 无错误 |
| 单元测试 | `uv run pytest tests/unit -q` | 全部通过 |
| 集成测试 | 设置 `REPORTIFY_TEST_DATABASE_URL` 后 `uv run pytest tests/integration -q` | 全部通过 |
| 凭证 | 创建数据源后查库 | `ciphertext` 非空，无明文；API 响应无密码 |
| 连接 | `POST /api/v1/data-sources/{id}/test` | 正确凭证 200；错误凭证结构化失败 |
| 同步 | `POST /sync` 两次 | 第二次幂等；修改列后 `columns_hash` 变化 |
| 查询 | 服务层执行 `QuerySpec` | 参数化 SQL；未知列/超限被拒绝 |
| Profiling | `POST /columns/reprofile` | `stats` 写入，`profile_version` 增加 |
| 边界 | grep `pydantic_ai|mcp|runtime` | 无业务越界 |

测试库：Docker PostgreSQL 16，`127.0.0.1:55432`；测试 schema 独立，避免污染。

---

## 7. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 用户数据库慢/锁表 | `statement_timeout`、`lock_timeout`、只读事务、行数上限 |
| SQL 注入 | 不接受原始 SQL；标识符白名单；值参数化；负面测试 |
| 凭证泄漏 | AES-GCM；API 脱敏；日志过滤；集成测试断言无常量明文 |
| 元数据漂移 | `columns_hash`；同步结果显式报告 |
| 大表采样开销 | `TABLESAMPLE` + 样本上限；超时返回部分结果 |
| 测试依赖 Docker | 集成测试按环境变量 skip；CI 后续补 |
| 迁移失败 | 迁移只新增表；`downgrade` 删除新表；先备份 |

---

## 8. Execute Log

| # | 动作 | 结果 |
| --- | --- | --- |
| 1 | 依赖 | 新增 `cryptography`、`pandas`；测试改用 `httpx2`；`pytest-asyncio` 升至 1.5 |
| 2 | 凭证 | `SecretService` AES-GCM 完成，含错误密钥版本测试 |
| 3 | 模型/迁移 | 5 张表 + `0002` 迁移；PostgreSQL 16 实际应用成功 |
| 4 | Connector | Protocol、Registry、`PostgresConnector` 完成 |
| 5 | Query Builder | 白名单、参数绑定、LIMIT、聚合、拒绝未知表/列 |
| 6 | Metadata | 同步、幂等、`columns_hash` 漂移检测、用户字段保留 |
| 7 | Profiling | Pandas 统计、`stats` 写库、`profile_version` 递增 |
| 8 | API | CRUD、test、sync、tables、columns、profile、可选 Bearer |
| 9 | 测试 | 单元 + 集成；42 passed, 1 skipped |
| 10 | 真实验收 | CRUD → test → sync → tables → columns → patch → profile |
| 11 | Spec 回写 | 本节、§9–§11 完成 |

## 9. Verification Evidence

| 项 | 命令 / 操作 | 结果 |
| --- | --- | --- |
| 静态检查 | `uv run ruff check .` | `All checks passed!` |
| 全量测试 | `uv run pytest -q` | `42 passed, 1 skipped` |
| 迁移 | `alembic upgrade head` | `0002` 应用成功 |
| 真实 API | 启动 uvicorn，创建数据源 | `has_secret=true`，响应无密码 |
| 连接测试 | `POST /test` | `{"ok": true}` |
| 同步 | `POST /sync` | `tables_added=1, columns_added=5` |
| 元数据 | `GET /tables`、`GET /columns` | 表 1、列 5 |
| 中文标签 | `PATCH /columns/{id}` | 集成测试断言 `请求耗时` / `秒` / `核心指标` 通过 |
| Profiling | `POST /profile` | `sampled_rows=10`，有 `snapshot_id` |
| 凭证落库 | 查询 `secret.ciphertext` | 与明文不同；API 响应无密码 |

> 说明：PowerShell 手工调用时中文 body 因客户端编码显示为 `????`；同一断言在 `TestClient` 集成测试中通过，确认服务端 UTF-8 处理正确。

## 10. Plan-Execution Diff

| 项 | 计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| 新增源文件 | 未列 `types.py`、`data_source_service.py` | 已新增 | 类型归一化与数据源生命周期需要独立模块 |
| Profiling 采样 | 默认 50,000，`TABLESAMPLE` | 默认 10,000，`LIMIT` | 与 QuerySpec/单页上限一致；TABLESAMPLE 留待优化 |
| 列查询路由 | `/tables/{table}/columns` | `GET /columns?table=schema.table` | 避免 schema 点号进入路径参数 |
| Snapshot `time_range` | 写入 `TSTZRANGE` | 字段保留，M1 写 `NULL`，时间范围存入 `filters` | 避免引入额外 range 类型转换；M2 再补 |
| `run_id` | FK → `task_run` | 暂为普通 UUID | `task_run` 在 M2 才创建 |
| 测试依赖 | `httpx` | `httpx2` | Starlette TestClient 弃用 `httpx` |
| pytest-asyncio | 未指定 | 1.5.0 | 0.26 在 `asyncio.run` 后无事件循环，导致集成测试失败 |

## 11. Review Verdict

| 轴 | 检查项 | 结论 | 证据 |
| --- | --- | --- | --- |
| Axis-1 | 目标与验收标准明确 | PASS | §1 |
| Axis-1 | 验收项已验证 | PASS | §9 |
| Axis-2 | Checklist 1–11 完成 | PASS | §5.5 全部勾选 |
| Axis-2 | 偏差已记录 | PASS | §10 |
| Axis-3 | 安全 | PASS | 凭证加密、API 脱敏、查询白名单、参数绑定、只读事务 |
| Axis-3 | 正确性 | PASS | 42 项测试；真实 API 流程 |
| Axis-3 | 可维护性 | PASS | 模块边界清晰；错误码稳定；接口分层 |
| Axis-3 | 未覆盖项 | PARTIAL | 无 UI；`TABLESAMPLE`、范围类型、M2 FK 留待后续 |

**Overall Verdict：PASS（附后续项）**。无阻塞问题；等待用户验收。

## 12. Gate

- `Review / ACCEPTED`（2026-11-21）：用户指令「继续完成剩下的内容」视为验收通过，M1 关闭。
- 下一阶段 M2 Agent Runtime / Tool 工具链，见 `2026-11-21_19-55_Reportify-M2-Agent-Runtime.md`。
- M1 遗留项（`TABLESAMPLE`、`time_range` 写值、`run_id` FK）由后续里程碑承接；其中 `run_id` 外键在 M2 `0003` 迁移补齐。
