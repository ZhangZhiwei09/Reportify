# 04 · 数据层：Connector、Profiling 与 Analysis

> 依赖：`08-data-model.md`、`03-tooling-and-mcp.md`。  
> 范围：数据访问抽象与最小分析契约；Profiling / Analysis Engine 的算法实现属于 §12+。

---

## 1. Purpose

定义 Reportify 如何**安全、可追溯**地读取用户数据，并把「取数」与「计算」拆成两个确定性步骤：

- Data Connector：只负责连接、发现、受限查询、分页。
- Profiling / Analysis Engine：只负责基于取回数据的确定性统计。

LLM 不接触 SQL 执行，也不做数值计算。

---

## 2. Non-Goals

- MVP 只实现 PostgreSQL；MySQL / CSV / Excel / REST 只留接口。
- 不引入 Polars / DuckDB；但分析接口不绑定 Pandas 类型。
- 不做数据同步、ETL、数据仓库建模。
- 不自动推断字段业务含义（例如 `status=1` 不等于「成功」）。

---

## 3. 数据访问抽象

```python
class DataConnector(Protocol):
    async def test_connection(self) -> Health: ...
    async def inspect_schema(self, schema: str | None = None,
                             table: str | None = None) -> list[TableSchema]: ...
    async def fetch_page(self, query: QuerySpec, limit: int, offset: int) -> Page: ...
    async def execute(self, query: QuerySpec) -> ResultSet: ...
    async def close(self) -> None: ...

class ConnectorRegistry:
    def get(self, data_source_id: UUID) -> DataConnector: ...
    async def close_all(self) -> None: ...
```

`ConnectorRegistry` 按 `data_source_id` 管理连接池；Runtime 只通过它获取 Connector，不持有连接。

### 3.1 QuerySpec

```python
class ColumnRef(BaseModel):
    name: str                      # 必须存在于 metadata，禁止任意标识符

class Filter(BaseModel):
    column: str
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte",
                "in", "not_in", "between", "is_null", "like"]
    value: Any                     # 参数绑定，不拼 SQL

class Aggregate(BaseModel):
    func: Literal["count", "sum", "avg", "min", "max", "stddev"]
    column: str | None             # count(*) 可为空
    alias: str

class QuerySpec(BaseModel):
    table: str                     # schema.table，必须在 allowlist
    columns: list[ColumnRef] = []
    filters: list[Filter] = []
    time_range: TimeRange | None = None
    group_by: list[ColumnRef] = []
    aggregates: list[Aggregate] = []
    order_by: list[OrderBy] = []
    distinct: bool = False
    limit: int = 1000              # 上限 10000
    offset: int = 0
```

**硬约束**：

- 不接受原始 SQL 字符串。
- 表名、列名必须来自 `table_metadata` / `column_metadata`。
- 所有值走参数绑定。
- 单条语句，禁止多语句与 DDL/DML。

### 3.2 结果类型

```python
class TableSchema(BaseModel):
    schema_name: str
    table_name: str
    table_type: str
    row_estimate: int | None
    columns: list[ColumnSchema]

class ColumnSchema(BaseModel):
    name: str
    native_type: str
    normalized_type: str
    nullable: bool
    is_primary_key: bool

class ResultSet(BaseModel):
    columns: list[ColumnSchema]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    lineage: Lineage
    snapshot_id: UUID

class Page(BaseModel):
    rows: list[list[Any]]
    offset: int
    total_estimate: int | None
    has_more: bool
```

---

## 4. PostgreSQL Connector

### 4.1 连接与驱动

- SQLAlchemy 2.0 async + `asyncpg`（`postgresql+asyncpg://`）。
- 每个数据源维护小型连接池（2–5），空闲回收；不共享用户连接与系统元数据库连接。
- 连接参数：`connect_timeout`、`command_timeout`、`ssl`。
- 凭证从 `secret` 解密后只在连接建立时使用，不进入日志。

### 4.2 只读与超时

| 控制 | 默认 | 说明 |
| --- | --- | --- |
| 只读事务 | 强制 | `BEGIN READ ONLY`；建议使用只读数据库角色 |
| `statement_timeout` | 30s | 单条查询 |
| `lock_timeout` | 5s | 避免阻塞业务库 |
| `idle_in_transaction_session_timeout` | 60s | 防泄漏 |
| 单页行数 | 1000 | 最大 10000 |
| 分析总行数 | 1,000,000 | 超过则抽样或拒绝 |
| 单 run 内存上限 | 1 GB | 进程内配额，超限终止 |

### 4.3 结构发现

- 通过 `information_schema.columns` + `pg_catalog` 获取表、列、主键、注释、行数估算。
- 只允许业务 schema；默认排除 `pg_catalog`、`information_schema`、`pg_toast`。
- `row_estimate` 来自统计信息，不保证精确；精确行数只在必要时 `count(*)`。
- 结果写入 `table_metadata` / `column_metadata`；`columns_hash` 用于漂移检测。

### 4.4 查询构造

```python
class SafeQueryBuilder:
    def build(self, spec: QuerySpec) -> tuple[str, dict[str, Any]]:
        # 1. 校验表/列在 allowlist
        # 2. 使用方言 identifier preparer 引用标识符
        # 3. 值全部参数化
        # 4. 强制 LIMIT
        # 5. 返回 (sql, params)
        ...
```

禁止：

- 字符串拼接值或标识符。
- `SELECT *` 未经列裁剪进入分析。
- 子查询递归、`UNION` 注入、注释绕过。
- 多语句（`;`）与 `COPY`、`SET ROLE` 等。

### 4.5 类型归一化

| 原生类型 | `normalized_type` |
| --- | --- |
| smallint / int / bigint / numeric / decimal / real / double | `numeric` |
| date / timestamp / timestamptz / time | `temporal` |
| boolean | `boolean` |
| json / jsonb | `json` |
| text / varchar / char / uuid / enum | `text`（profiling 后可标为 `categorical`） |
| 其他 | `unknown` |

`categorical` 是统计结果（低基数），不是业务语义。用户标签只影响展示与解释。

### 4.6 分页

- 优先 keyset 分页（按主键或时间列）；无合适键时使用 `LIMIT/OFFSET`，并限制最大 offset。
- `fetch_dataset` 只读取已生成的 `snapshot_id`，不重新解释用户意图。

---

## 5. Profiling 最小契约

```python
class ColumnProfile(BaseModel):
    name: str
    normalized_type: str
    null_ratio: float
    distinct_count: int | None
    min: Any | None
    max: Any | None
    mean: float | None
    std: float | None
    top_values: list[tuple[Any, int]] = []
    sample_values: list[Any] = []
    warnings: list[str] = []

class ProfileResult(BaseModel):
    table: str
    row_count_estimate: int | None
    sampled_rows: int
    columns: list[ColumnProfile]
    generated_at: datetime
    lineage: Lineage
```

规则：

- 采样上限默认 50,000 行；优先 `TABLESAMPLE SYSTEM`，视图用 `LIMIT`。
- `top_values` / `sample_values` 各限 20 条；疑似 PII 的字段只返回类型与统计，不返回样本。
- 不推断业务含义；`status` 只描述为「5 个分类值」。
- 结果写入 `column_metadata.stats`，`profile_version` 递增。

---

## 6. Analysis Engine 最小契约

> 算法实现属于 §12+；本层只约束输入、输出与可替换性。

```python
class AnalysisEngine(Protocol):
    def trend(self, frame: DataFrame, req: TrendRequest) -> AnalysisResult: ...
    def distribution(self, frame: DataFrame, req: DistributionRequest) -> AnalysisResult: ...
    def compare(self, current: DataFrame, previous: DataFrame, req: CompareRequest) -> AnalysisResult: ...
    def anomalies(self, frame: DataFrame, req: AnomalyRequest) -> AnalysisResult: ...
    def correlation(self, frame: DataFrame, req: CorrelationRequest) -> AnalysisResult: ...
```

`AnalysisResult` 必须包含：

| 字段 | 说明 |
| --- | --- |
| `series` / `table` | 图表可直接消费的数据 |
| `metrics` | 关键统计量（均值、变化率、CV、p 值等） |
| `lineage` | 数据源、SQL、范围、样本量、耗时、口径 |
| `warnings` | 样本不足、空值过多、方差为 0 等 |
| `engine` | `pandas`（未来可替换） |

规则：

- 输入是 Connector 返回的数据或已生成的 DataFrame，不接受 LLM 生成的代码。
- 所有计算确定性；相同输入与参数必须得到相同结果。
- 结果中的每个数字可追溯到 `snapshot_id`。

---

## 7. Lineage 与 Snapshot

每次查询/分析生成 `dataset_snapshot`：

| 字段 | 来源 |
| --- | --- |
| `sql` | 构造后的只读 SQL |
| `params` | 绑定参数（敏感值脱敏） |
| `time_range` | 时间过滤 |
| `filters` | 结构化过滤 |
| `row_count` | 实际读取行数 |
| `query_fingerprint` | SQL + 参数 + 范围的 hash |
| `purpose` | inspect / profile / analysis / report |

报告中的图表与指标必须引用 `snapshot_id` 或工具调用记录；没有 lineage 的数字不得进入报告。

---

## 8. 性能策略

| 场景 | 策略 |
| --- | --- |
| 聚合类分析 | 尽量下推到 SQL（`group_by` + `aggregates`），只取聚合结果 |
| 分布/异常 | 取必要列与时间范围；超过 100 万行先抽样 |
| 多字段画像 | 单次采样计算所有列，避免逐列查询 |
| 分页展示 | preview 最多 1000 行；完整数据留在 Python 侧 |
| 重复查询 | 相同 `query_fingerprint` 在短期 TTL 内复用 snapshot 摘要（Redis，可选） |
| 大结果 | 流式读取 + 分块转换，避免一次性构造巨大 DataFrame |

Pandas 是 MVP 引擎；接口不暴露 Pandas 类型给上层工具契约。

---

## 9. 安全

| 风险 | 措施 |
| --- | --- |
| SQL 注入 | 不接受原始 SQL；标识符 allowlist；值参数化 |
| 越权访问 | 使用最小权限只读账号；schema allowlist |
| 慢查询拖垮业务库 | statement_timeout / lock_timeout / 行数上限 |
| 凭证泄露 | `secret` 加密；日志脱敏 |
| PII 外泄 | 样本值脱敏；报告只展示聚合结果 |
| 数据漂移 | `columns_hash` 校验；运行前检查 |
| 资源耗尽 | 内存配额、分块读取、单 run 超时 |

---

## 10. Failure Modes

| 场景 | 错误码 | 处理 |
| --- | --- | --- |
| 认证失败 | `auth_failed` | 提示更新凭证；不重试 |
| 权限不足 | `permission_denied` | 提示只读权限或 schema allowlist |
| 查询超时 | `timeout` | 缩小范围或抽样；可重试一次 |
| 连接失败 | `connection_failed` | 重试 1 次；仍失败标记数据源 error |
| 结果超限 | `too_many_rows` | 强制抽样或要求加过滤条件 |
| Schema 漂移 | `schema_changed` | 要求重新同步元数据 |
| 类型不支持 | `unsupported_type` | 跳过该列并告警 |

---

## 11. Open Questions

1. 驱动选择 `asyncpg` 还是 `psycopg 3`？两者在超时与取消语义上有差异，需要 PoC。
2. Profiling 采样用 `TABLESAMPLE` 还是 `ORDER BY random()`？后者在大表上代价高。
3. 聚合下推的覆盖范围：MVP 是否只支持单表 `group_by`？
4. PII 检测是否引入规则库，还是只做保守的样本脱敏？
5. 是否需要保存分析结果的统计摘要，以支持报告离线复现？
