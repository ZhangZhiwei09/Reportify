# Reportify 架构设计 V3 — Spec

> 层级：Feature Spec（本次任务）
> 路径：`mydocs/specs/2026-11-21_17-32_Reportify-Architecture-V3.md`

---

## 0. 状态

| 字段 | 值 |
| --- | --- |
| Phase | `Closed` |
| Status | `LOCKED` |
| Approval | `Plan Approved` → 用户验收通过（2026-11-21） |
| 任务单元 | 完成 Reportify V3 架构设计文档（模块边界 / 数据模型 / 执行流程 / MCP / 记忆 / 上下文 / 报告 / 工程方案），不写业务代码 |
| 当前阻塞 | 等待 PydanticAI / DeepSeek / MCP 事实核查回填；等待 Plan 批准 |
| 用户决策 | 范围=只设计 §1–§11 已有章节；交付=多篇文档；深度=模块+接口+核心模型；创建 AGENTS.md + CLAUDE.md |

---

## 1. 最终目标与当前任务单元

**最终目标**：为 Reportify（通用型 AI 数据分析与可视化 Agent 平台）形成一套可实现、可维护、可演进的 V3 架构设计，覆盖 `prompt.md` §1–§11 的核心模块，并对 §12+ 给出最小接口边界。

**当前任务单元**：只做架构设计与技术决策，交付可评审的设计文档；不写 Python 业务代码、不实现管理台、不做部署。

**成功标准（可验证）**：

1. 每个模块有明确职责、边界、输入输出、依赖方向，且有明确的「不做什么」。
2. 核心数据模型（Conversation / Message / Analysis Task / Data Source / Dataset Snapshot / MCP Server / MCP Tool / Skill / Template / Run / Report Ref 等）有字段级定义与关系。
3. Agent 执行主链路有端到端时序（含工具授权、循环控制、失败恢复）。
4. 明确 PydanticAI / DeepSeek / MCP SDK 的真实能力与降级路径，不基于想象。
5. 明确 MVP 范围与后续演进的切口，避免过度设计。

**非目标（本次不做）**：

- 业务代码、前端页面实现、CI/CD、压测、线上运维手册。
- 多租户、复杂 RBAC、微服务拆分。
- 具体 Prompt 文案的最终定稿（只给机制与结构）。

---

## 2. In / Out of Scope

### In Scope

- 模块化单体的模块划分与依赖规则。
- Agent Runtime 编排模型（PydanticAI 能力映射）。
- 工具统一注册、授权、审计、执行控制。
- Data Connector（MVP PostgreSQL）与 Profiling/Analysis 最小契约。
- MCP Hub / MCP Client Runtime（Streamable HTTP）。
- Agent Workspace、Skills、Report Template。
- Conversation / Analysis Task 的多轮与任务模型。
- Report Schema 与来源追溯（Lineage）契约。
- 跨切面的数据模型与工程方案。
- 工程结构、测试策略、Docker 部署、MVP 里程碑。

### Out of Scope

- 业务功能代码与 UI 实现。
- Memory、Context 压缩、Data Profiling / Analysis Engine 内部实现、Report Engine / Revision、Scheduler（仅最小接口或边界说明）。
- 多数据源 Connector 的具体实现（只留接口）。
- Polars/DuckDB、沙箱执行 Skill 脚本的完整实现（只给边界与接入点）。

---

## 3. Context Sources

| # | 来源 | 说明 |
| --- | --- | --- |
| 1 | `prompt.md`（V3，715 行） | 用户提供的设计任务书；**在 §11.2 `current` 处截断** |
| 2 | `docs/reportify-design-demos/reportify-system.html` | 管理台高保真原型：分析工作台 / 报告库 / 定时任务 / 数据源 / 字段元数据 |
| 3 | `docs/reportify-design-demos/reportify-dashboard.html` | 报告产物样例：KPI、ECharts、来源与计算口径 |
| 4 | `docs/reportify-design-demos/direction-1/2/3-*.html` | 三种视觉方向；direction-2 列出七个模块叙事 |
| 5 | git log | `docs: v3` 更新 prompt.md；设计 demo 分两次提交 |
| 6 | PydanticAI / DeepSeek / MCP 官方文档 | 已核查，见 §4.3（核查日 2026-11-21） |

---

## 4. Research Findings

### 4.1 产品形态与 UI 基线（来自设计 demo）

管理台已表达出的信息架构（可作为架构的 UI 消费方约束）：

- **工作区**
  - 新建分析：会话流 + Agent 执行过程（实时推送，WebSocket 标注）+ 产物卡片。
  - 报告库：报告列表（名称、类型即时/定时、数据源、样本量、生成时间、状态、查看/下载）。
  - 定时任务：Cron、启停、上次/下次执行、生成数量、分析需求；由 ARQ + Redis 驱动，与 Agent Runtime 解耦。

- **配置**
  - 数据源：PostgreSQL 连接、只读模式、Schema、表清单、主分析表、凭证存储方式。
  - 字段元数据：识别类型（数值/时间/分类/文本）、展示名、单位、用户标签、描述；明确「标签只辅助展示与解释，不是分析前置条件」。

- **报告产物**：标题 + 用户原始需求 + 数据源/范围/样本量/生成时间/耗时 + KPI 行 + 分节图表 + 每图「数据来源（SQL/工具）+ 计算口径 + 耗时」+ 报告 ID。

**架构含义**：

- 需要实时执行事件流（最终采用 SSE）与可持久化的 Execution/Message 事件模型。
- 报告必须携带 lineage：SQL / 工具调用 / 参数 / 样本量 / 计算口径。
- 字段元数据是「可选增强」，系统不能依赖用户先标注业务语义。
- 定时任务与交互式分析共用同一 Runtime，但触发与执行隔离。

### 4.2 需求文档截断（关键事实）

`prompt.md` 在 **§11.2 Analysis Task → `current`** 处中断。以下章节在源文档中缺失：

- §11.2 剩余字段（current_state / report refs / version / timestamps 等）
- §12 起的 Memory Management、Context Management、Data Profiling、Analysis Engine、Report Engine、Report Revision、Scheduler、Observability
- 工程结构、配置、测试、数据模型、API 设计、里程碑等后续章节

**影响**：不能假装需求完整。需要用户确认：由我基于已有内容补全提案，还是用户补充原文。

### 4.3 技术事实核查（PydanticAI / DeepSeek / MCP）

> 原则：只采纳官方文档可证实的能力；未证实项标注「待 PoC 验证」。核查日：2026-11-21。实现前需按来源 URL 复验。

#### 4.3.1 DeepSeek API（官方文档）

| 事实 | 结论 | 设计影响 |
| --- | --- | --- |
| 模型 | `deepseek-flash`（V4.1-Flash-1017）、`deepseek-v4-pro`（V4-Pro-0813）；1M 上下文 / 384K 最大输出 | 模型名必须配置化，禁止硬编码 |
| 下线 | `deepseek-chat` / `deepseek-reasoner` 已于 2026-07-24 下线 | 设计文档不得再引用旧模型名 |
| Tool calling | 两个模型均支持；思考模式默认开启 | 可作为 Agent 主通道 |
| 思考模式硬约束 | 带 `tools` 时，所有历史轮 `reasoning_content` 必须原样回传，否则 400；`tool_choice=required` / 指定函数返回 400 | 消息持久化必须保留 provider 原始字段；Context 重建要按协议回放 |
| 结构化输出 | 仅 `response_format={"type":"json_object"}`，**无 `json_schema`**；非 JSON 输出会被替换为空格且 `finish_reason=stop` | 不能依赖原生 schema 约束；Pydantic 校验 + 失败重试是必需路径 |
| strict 模式 | Beta，`/beta` 端点；不支持 minLength/maxLength/minItems/maxItems；所有属性必须 required，`additionalProperties:false` | 可作为可选强校验，不作为唯一依赖 |
| 参数限制 | 思考模式 temperature 无效；frequency/presence penalty 已弃用；无 n/seed；stream + tools 可同时用 | Provider 适配层需过滤无效参数 |
| 稳定性 | 10 分钟未开始推理即断开；429（限流）/503（过载）需重试；并发上限 flash 2500 / pro 500 | Runtime 必须有超时、重试、并发闸门 |
| 历史注入限制 | Chat Completions 不支持在历史中间插入 tool call 消息 | 分支/回放/工具结果重写需改用 Responses API 或 Anthropic 兼容端点 |

#### 4.3.2 MCP（Python SDK v2.3.0 / 协议 2026-07-28）

| 事实 | 结论 | 设计影响 |
| --- | --- | --- |
| 传输 | stdio / Streamable HTTP / SSE；SSE 不再用于新建 | MVP 只做 Streamable HTTP |
| 生命周期 | `async with Client(...)` 即全生命周期，无 connect/close 对；默认 read timeout 300s | 连接管理器必须与请求生命周期绑定，不能长期持有裸连接 |
| 鉴权 | `streamable_http_client(url, http_client=...)` 不接受 headers/timeout；用 `httpx2.AsyncClient(headers=..., auth=OAuthClientProvider)` | 凭证注入在 HTTP client 层，不写在 URL |
| 握手 | 2026-07-28 取消 `initialize`，改用 `ClientSession.discover()`；`initialize()` 仅兼容旧服务器 | 连接探测要同时支持新/旧协议 |
| Session/重连 | 新协议无 `Mcp-Session-Id`、无 `Last-Event-ID` 恢复；可用 `prior_discover` 省握手 | 不能设计「断点续传工具流」；重连=重新调用 |
| 结果 | `content` 为 Text/Image/Audio/ResourceLink/EmbeddedResource 联合 + `structured_content` + `is_error` | 工具结果必须按类型处理并限制大小 |
| 错误语义 | 超时 → `MCPError(-32001)`；`ToolError` → `is_error=True`（模型可自愈）；`MCPError` → 客户端抛异常；未知工具 → `is_error=True` | 重试策略按错误类型分层，不能只看 HTTP 状态码 |
| OAuth | 服务端实现 TokenVerifier + RFC 9728 PRM；客户端 `OAuthClientProvider`（`httpx2.Auth`）；stdio 无 OAuth | OAuth 可作为后续；stdio 必须沙箱化 |
| 安全 | 官方列出 confused deputy、token passthrough、OAuth 发现链 SSRF、本地 server 注入、授权 URL 校验；工具 annotations 视为不可信 | SSRF 防护覆盖发现链路，不只校验 server URL |
| PydanticAI 集成 | PydanticAI 的 MCP 客户端基于 **FastMCP**（`fastmcp-slim[client]`），不是官方 `mcp` SDK；`MCPToolset(url)` 默认 2026-07-28 | 管理面与 Agent 面连接实现要分开，不能混用连接对象 |

#### 4.3.3 PydanticAI（v2.71.0，2026-11-19）

| 事实 | 结论 | 设计影响 |
| --- | --- | --- |
| 版本 | `pydantic-ai 2.71.0`；V2.0.0 于 2026-06-23 发布；Python >=3.11 | 设计文档只写 V2 API，禁止使用 V1 类名 |
| Agent 构造 | `Agent(model, *, output_type, instructions, system_prompt, deps_type, retries={'output':2,'tools':1}, tools, toolsets, capabilities, max_concurrency, tool_timeout, end_strategy='graceful')` | `usage_limits` 不在构造器；`retries` 取代 `output_retries/tool_retries` |
| 依赖注入 | `RunContext[Deps]`，`ctx.deps`；`deps_type` 默认 `object` | RuntimeDeps 承载连接、注册表、任务上下文 |
| 工具 | `@agent.tool` 首参必须 `RunContext`；`@agent.tool_plain` 无 ctx；`ModelRetry` 可重试，`ToolFailed` 终态 | 内置工具按此实现；异常语义决定重试 |
| 动态工具集 | `FunctionToolset(...).filtered()/.prefixed()/.prepared()/.renamed()/.approval_required()/.defer_loading()`；`for_run/for_run_step` | 按任务与授权过滤工具的正规钩子 |
| MCP | 单一 `MCPToolset(client)`，首参推断传输；`max_retries`、`tool_error_behavior`、`read_timeout`（默认 5 分钟）、`cache_tools`、`include_instructions=False`；`.filtered()/.prefixed()` | Agent 面统一用 MCPToolset；管理面可单独用 FastMCP Client |
| 生命周期 | `async with agent:` / `async with toolset:`；不显式进入则按需自动开关 | 不能用长期共享的裸连接；按 run 或短生命周期管理 |
| 结构化输出 | 默认 `ToolOutput`；`NativeOutput` 仅 Responses API；`PromptedOutput` 可用；`output_validator` + `ModelRetry`；默认输出重试 1 | DeepSeek Chat Completions 用 ToolOutput/PromptedOutput，不依赖 json_schema |
| 多轮历史 | `message_history=`，`result.new_messages()/all_messages()`；`ModelMessagesTypeAdapter` 序列化；`sanitize_messages()` | 消息表存 app 消息 + PydanticAI JSON；恢复前清洗 |
| 执行控制 | `UsageLimits(request_limit=50, tool_calls_limit, input/output/total_tokens_limit, cost_limit)`；`CancellationToken`、`ctx.cancel()`、`timeout=` | 所有限制在 run 上；超限抛 `UsageLimitExceeded`，超时 `RunTimedOut` |
| 事件流 | `agent.run_stream_events()` 必须作 async CM；`agent.iter()` 产出 `AgentRun` 节点；事件含 `FunctionToolCallEvent/ResultEvent`、`OutputTool*`、`AgentRunResultEvent` | 事件流是持久化与 UI 推送的统一来源 |
| 权限前置 | `requires_approval=True` → `DeferredToolRequests`；capability hook `before_tool_execute`；`filtered()` 在请求前隐藏工具 | 三层：隐藏 → 审批 → 执行前二次校验 |
| 可观测性 | `Instrumentation` capability / `Agent.instrument_all()`；纯 OTel；Langfuse 无官方专页（未确认） | 以 OTel 为基线，Langfuse 通过 OTLP 接入需 PoC |
| 模型接入 | `OpenAIChatModel` + `DeepSeekProvider`；`'deepseek:deepseek-flash'`；DeepSeek 默认 thinking，thinking 开启时拒绝强制 tool_choice | 报告 Schema 生成时可设 `thinking=False`；模型与参数配置化 |
| 并发 | 同一 Agent 可并发 run；`max_concurrency`；MCPToolset 单实例单身份；跨 Task 复用无官方保证 | Runtime 使用单例 Agent + 并发上限；MCP 按 run 派生 |

**关键结论**：V2 中 `Agent(usage_limits=)`、`Agent(output_retries=)`、`MCPToolset(tool_filter=/prefix=)` 均不存在；`MCPServerStdio/SSE/StreamableHTTP`、`OpenAIModel` 已改名。设计文档如出现这些名字即为错误。

### 4.4 仓库现状

- 根目录仅 `README.md`（内容仅标题）与 `prompt.md`。
- 无 `AGENTS.md` / `CLAUDE.md` / `.cursorrules` 等项目级 Agent 规则文件。
- 无 `mydocs/`、无源码目录、无 `pyproject.toml`。
- 设计 demo 中有 3 个未跟踪文件（system/dashboard 的 html+png），当前工作区存在未提交内容；本次只读，不做任何 git 操作。

---

## 5. User Decisions（2026-11-21）

| # | 决策 | 对设计的影响 |
| --- | --- | --- |
| D1 | **只设计已有章节 §1–§11** | §12+（Memory / Context / Data Profiling / Analysis Engine / Report Engine / Revision / Scheduler / Observability）不做详细设计，另开任务 |
| D2 | 交付 **多篇文档** | `docs/architecture/` 下按主题拆分 + 一篇索引 |
| D3 | 深度 = **模块 + 接口 + 核心模型** | 含职责边界、关键类/函数签名、核心数据模型字段级、端到端时序；不含完整 API 路由表与 DDL |
| D4 | 创建 **AGENTS.md + CLAUDE.md** | 写入 SDD-RIPER 路由、项目边界、技术基线、文档规范 |

**范围一致性约定**：§10.1 的工具清单引用了 `profile_dataset` / `analyze_trend` / `generate_report` 等，但对应模块（Data Profiling / Analysis Engine / Report Engine）属 §12+，不在本次详细设计范围。处理方式：

- 仅在 §10 / §11 文档中把它们列为「外部接口契约（最小假设）」：工具名、输入/输出边界、lineage 必填项；
- 标注 `Out of scope — future spec`，不展开内部算法、存储与实现。

## 6. Remaining Open Questions（非阻塞，按默认执行）

1. 报告语言：默认中文、可配置（模板与 USER.md 均可覆盖）。
2. 管理台新增视图（MCP / Skills / Templates / 会话管理）纳入架构文档的「UI 消费方与 API 需求」章节，不写前端实现。
3. 设计文档语言：中文（代码、接口名、路径保持英文）。

## 7. Innovate

**跳过原因**：技术基线、UI 原型和官方 API 事实已把主要方案空间压缩到可推荐范围；高分歧点不单独开 Innovate，改为在 Plan 中给出「推荐方案 + 备选方案」，你在 Plan 评审时可直接覆盖。

### 7.1 关键决策记录（待 Plan 批准）

| ID | 决策 | 推荐方案 | 备选 / 取舍 |
| --- | --- | --- | --- |
| D-01 | 交互式 run 执行拓扑 | FastAPI 进程内异步执行，SSE 推送事件；ARQ 只跑定时/长任务 | 全部 run 进 ARQ + Redis pub/sub：隔离更好，但本地部署复杂度和延迟更高 |
| D-02 | Agent 编排 | 单 Agent + 工具循环；分析计划作为结构化事件与 Task 字段，不强制两阶段 | Planner/Executor 两阶段：更可控，但多一次模型调用且易过度设计 |
| D-03 | 工具暴露与授权 | 每次 run 构造 filtered FunctionToolset + 写入类工具 `requires_approval` + 执行前 Registry 二次校验 | 仅靠 Prompt 约束：不可审计，否决 |
| D-04 | MCP 连接 | Agent 面 per-run `MCPToolset`（懒连接）；管理面独立 FastMCP Client 短连接 | 长期共享连接：受 v2 生命周期与单身份限制，跨任务复用无保证 |
| D-05 | 会话持久化 | 应用层 `message` 表 + PydanticAI `ModelMessage` JSON；`run_event` 表用于审计/回放 | 只存纯文本：无法恢复工具调用，否决 |
| D-06 | Workspace 配置 | 文件为源，DB 只存索引/审计；run 前加载，mtime/hash 缓存 | 全存 DB：可视化编辑方便，但违背文件化配置的定位 |
| D-07 | 报告契约 | Template YAML → Pydantic；只定义 Report Schema 与 lineage 契约，渲染器属 §12+ | 本次设计渲染器：超出用户确认范围 |

---

## 8. Plan（Contract）

### 8.1 交付物清单

| # | 文件 | 内容 |
| --- | --- | --- |
| 1 | `docs/architecture/README.md` | 索引、阅读顺序、范围声明、术语表、决策记录入口 |
| 2 | `docs/architecture/01-system-overview.md` | 目标/非目标、设计原则、17 模块总览与本次范围标记、部署拓扑、端到端数据流、MVP 边界 |
| 3 | `docs/architecture/02-agent-runtime.md` | PydanticAI V2 映射、RuntimeDeps、run 生命周期、上下文装配、工具暴露、限制/取消/超时、事件模型、错误分类、持久化钩子 |
| 4 | `docs/architecture/03-tooling-and-mcp.md` | Tool Registry、内置工具契约、MCP Hub、MCP Client Runtime、授权状态机、审计、安全（SSRF/凭证/输出限制/不可信内容） |
| 5 | `docs/architecture/04-data-layer.md` | Data Connector 接口、PostgreSQL 实现约束、元数据/快照/lineage、Profiling 与 Analysis Engine 最小接口 |
| 6 | `docs/architecture/05-conversation-task.md` | Conversation / Message / AnalysisTask 模型、多任务、run 事件持久化、恢复、报告引用 |
| 7 | `docs/architecture/06-workspace-skills-templates.md` | SOUL / USER / AGENTS 职责与优先级、Skill 索引与渐进加载、Report Template Schema、安全边界 |
| 8 | `docs/architecture/07-api-and-ui.md` | FastAPI 路由组、SSE/WebSocket 事件、管理台 5+3 视图、单用户认证 |
| 9 | `docs/architecture/08-data-model.md` | 实体清单、字段表、关系、ER 图、PostgreSQL / Redis / 文件存储分工 |
| 10 | `docs/architecture/09-engineering.md` | 目录结构、uv/pyproject、配置、Alembic、测试、Docker Compose、可观测性、MVP 里程碑 |
| 11 | `AGENTS.md` + `CLAUDE.md` | 项目规则、SDD-RIPER 路由、技术基线、文档规范 |

### 8.2 每篇文档的固定结构

每篇包含：`Purpose` / `Non-Goals` / `Responsibilities` / `Interfaces` / `Data & State` / `Key Flows`（Mermaid）/ `Failure Modes` / `Security Notes` / `Open Questions`。

### 8.3 关键接口（文档中签名级描述，不写实现）

```python
class RuntimeDeps:            # run 级依赖
    session: AsyncSession
    workspace: WorkspaceSnapshot
    registry: ToolRegistry
    task: AnalysisTask
    connectors: ConnectorRegistry
    mcp: MCPHubClient

class AgentRuntime:
    async def run(self, req: RunRequest, deps: RuntimeDeps,
                  cancel: CancellationToken) -> AsyncIterator[RunEvent]: ...

class ToolRegistry:
    async def list_for_run(self, deps: RuntimeDeps) -> list[ToolSpec]: ...
    def resolve(self, name: str) -> ToolBinding: ...
    async def authorize(self, name: str, args: dict, deps: RuntimeDeps) -> AuthorizationDecision: ...

class MCPHubClient:
    async def test_connection(self, server_id: UUID) -> Health: ...
    async def discover_tools(self, server_id: UUID) -> list[MCPToolRecord]: ...
    async def call(self, server_id: UUID, tool: str, args: dict) -> ToolResult: ...

class WorkspaceLoader:
    def load(self) -> WorkspaceSnapshot: ...
    def skills_index(self) -> list[SkillMeta]: ...

class SkillLoader:
    def load(self, name: str) -> SkillContent: ...

class DataConnector(Protocol):
    async def inspect_schema(self) -> list[TableSchema]: ...
    async def fetch_page(self, query: QuerySpec, limit: int, offset: int) -> Page: ...
    async def execute_readonly(self, query: QuerySpec) -> ResultSet: ...

class ConversationService:
    async def append(self, msg: NewMessage) -> MessageRecord: ...
    async def history(self, conversation_id: UUID) -> list[ModelMessage]: ...

class TaskService:
    async def create(self, goal: str, conversation_id: UUID) -> AnalysisTask: ...
    async def update_state(self, task_id: UUID, state: TaskState) -> None: ...

class ContextAssembler:
    async def build(self, task: AnalysisTask, conversation_id: UUID,
                    workspace: WorkspaceSnapshot) -> list[ModelMessage]: ...

class EventPublisher:
    async def publish(self, run_id: UUID, event: RunEvent) -> None: ...
```

### 8.4 核心数据实体（字段级见 08-data-model.md）

`data_source` · `table_metadata` · `column_metadata` · `dataset_snapshot` · `conversation` · `message` · `analysis_task` · `task_run` · `run_event` · `tool_definition` · `tool_grant` · `tool_call_audit` · `mcp_server` · `mcp_tool_cache` · `skill_index` · `report_template_index` · `report_ref`（最小引用，§12+）· `workspace_audit`

### 8.5 Mermaid 图清单

1. 系统容器图（FastAPI / Worker / PG / Redis / MCP Server / LLM）。
2. 模块依赖图（17 模块，标注本次设计/仅接口）。
3. 交互式 run 时序图（请求 → 上下文 → Agent → 工具 → 事件 → 持久化）。
4. MCP 授权与调用时序图（发现 → 授权 → 过滤 → 执行 → 审计）。
5. Conversation / AnalysisTask 状态机。
6. ER 图（核心表与关系）。

### 8.6 执行顺序

1. `08-data-model.md`（其他文档的引用基础）
2. `01-system-overview.md` + `README.md`
3. `02-agent-runtime.md`
4. `03-tooling-and-mcp.md`
5. `04-data-layer.md`
6. `05-conversation-task.md`
7. `06-workspace-skills-templates.md`
8. `07-api-and-ui.md`
9. `09-engineering.md`
10. `AGENTS.md` + `CLAUDE.md`
11. 交叉一致性检查 + `REVIEW EXECUTE`

### 8.7 验收 checklist

- [ ] 范围严格限定 §1–§11；§12+ 只出现「最小接口契约」，并标注 `Out of scope`。
- [ ] 每篇包含固定结构（§8.2），无空章节。
- [ ] 不出现 V1 PydanticAI 类名（`MCPServer*`、`OpenAIModel`、`Agent(usage_limits=)` 等）。
- [ ] DeepSeek 模型名、JSON mode 限制、thinking 约束与官方事实一致。
- [ ] MCP 设计覆盖 v2 生命周期、错误语义、SSRF、工具 annotations 不可信、结果大小限制。
- [ ] 工具权限三层（隐藏 / 审批 / 执行前校验）在文档与时序图中一致。
- [ ] 数据模型字段与接口签名、事件类型跨文档一致。
- [ ] 每条关键结论可追溯到 `prompt.md`、设计 demo 或官方文档 URL。
- [ ] 所有 Mermaid 图可在 GitHub/VS Code 渲染。
- [ ] `AGENTS.md` / `CLAUDE.md` 创建完成且内容一致。
- [ ] 用户逐篇或整体验收通过。

### 8.8 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| PydanticAI / MCP 版本快速演进 | 文档记录核查日期与版本；接口层隔离；实现前 PoC 复验 |
| DeepSeek 思考模式与工具调用限制 | 报告 Schema 生成可关闭 thinking；ToolOutput + validator 重试；空 content 兜底 |
| §12+ 模块边界被反复拉扯 | 只给最小契约；新增需求另开 Spec |
| 文档过长、评审疲劳 | 每篇 ≤400 行；先评审 01/02/08，再批量评审其余 |
| 设计滑向实现 | 禁止代码实现；签名与模型字段为上限 |

---

## 9. Gate

- **当前**：`Plan` / `LOCKED` / 等待 `Plan Approved`。
- 收到精确字样 **`Plan Approved`** 后进入 `Execute`，按 §8.6 顺序写文档。
- 若需调整 D-01–D-07 或交付清单，请在批准前指出。

## 10. Checkpoint 热摘要

- Phase：`Closed` / `LOCKED`
- Approval：`Plan Approved` → 验收通过（2026-11-21）
- 目标：Reportify V3 架构设计文档（非代码）
- 进度：11 / 11（已验收）
- 下一步：M0 实现 Spec `mydocs/specs/2026-11-21_17-51_Reportify-M0-Bootstrap.md`

## 11. Execute Log

| # | 文件 | 动作 | 证据 |
| --- | --- | --- | --- |
| 1 | `docs/architecture/08-data-model.md` | 19 个实体、字段级定义、ER 图、索引、保留策略、安全与失败模式 | 文件已落盘 |
| 2 | `docs/architecture/01-system-overview.md` + `README.md` | 17 模块范围、容器拓扑、依赖规则、端到端流程、MVP 边界、索引 | 文件已落盘 |
| 3 | `docs/architecture/02-agent-runtime.md` | PydanticAI V2 映射、run 生命周期、上下文、工具暴露、预算、事件、错误 | 文件已落盘 |
| 4 | `docs/architecture/03-tooling-and-mcp.md` | Tool Registry、内置工具契约、MCP Hub/Runtime、授权、审计、安全 | 文件已落盘 |
| 5 | `docs/architecture/04-data-layer.md` | Connector/Registry、PostgreSQL 约束、查询构造、Profiling/Analysis 最小契约 | 文件已落盘 |
| 6 | `docs/architecture/05-conversation-task.md` | 会话/任务/运行模型、状态机、多任务、恢复 | 文件已落盘 |
| 7 | `docs/architecture/06-workspace-skills-templates.md` | 文件职责与优先级、Skills 渐进加载、Template Schema | 文件已落盘 |
| 8 | `docs/architecture/07-api-and-ui.md` | 路由组、SSE 契约、8 个视图、前端约束 | 文件已落盘 |
| 9 | `docs/architecture/09-engineering.md` | 目录、依赖、配置、测试、Docker、可观测、里程碑 | 文件已落盘 |
| 10 | `AGENTS.md` + `CLAUDE.md` | SDD-RIPER 路由、项目边界、技术基线、文档与验证规范 | 文件已落盘 |
| 11 | 一致性检查 | 修正 `plan` 事件命名、补充 `mcp_server.slug/options`、统一报告目录说明；禁用类名仅出现在「禁止」清单 | grep 检查 + 文件清单 |

**文件统计**：`docs/architecture/` 10 个 Markdown，共约 2,400 行；项目规则文件 2 个。

## 12. Plan-Execution Diff

| 项 | 计划 | 实际 | 原因 |
| --- | --- | --- | --- |
| 实体数量 | 18 | 18 业务实体 + 1 平台表 `secret` | 凭证统一加密存储 |
| `mcp_server` 字段 | 未含命名空间与运行参数 | 增加 `slug`、`options` | 工具命名与超时/速率限制需要落点 |
| 文档长度 | 每篇 ≤400 行（风险缓解项） | `08-data-model.md` 约 421 行，其余 ≤294 行 | 字段级模型信息密度高；不影响内容 |
| 事件命名 | `plan` 事件 + `analysis_plan` 消息 | 已统一 | 避免事件类型与消息类型混用 |
| 报告目录 | 未定 | 统一为独立 `reports_dir`，workspace 不存放产物 | 配置与产物分离 |

## 13. Review Verdict

### 13.1 Review Matrix

| 轴 | 检查项 | 结论 | 证据 |
| --- | --- | --- | --- |
| Axis-1 规格质量 | 目标、In/Out、验收标准是否明确 | PASS | Spec §1–§2、§8.7 |
| Axis-1 | 范围是否严格限定 §1–§11 | PASS | 全部文档标注 out of scope |
| Axis-1 | 验收是否已证明 | PARTIAL | 文件已落盘、结构完整；用户验收待完成 |
| Axis-2 规格-产出一致性 | 计划文件是否全部产出 | PASS | 11/11 |
| Axis-2 | 字段/事件/状态跨文档一致 | PASS | 修正 `plan` 事件、`slug/options`、`reports_dir` 后一致 |
| Axis-2 | 未授权偏差 | PASS | 偏差均记录于 §12 |
| Axis-3 文档内在质量 | 官方事实准确性 | PASS（待实现前复验） | Spec §4.3 记录版本、来源与限制 |
| Axis-3 | 安全覆盖 | PASS | 只读、默认拒绝、SSRF、凭证、审计、输出限制 |
| Axis-3 | Mermaid 可渲染 | 未验证 | 未实际在 GitHub/VS Code 打开渲染 |
| Axis-3 | 文档长度 | PARTIAL | `08` 约 421 行，略超 400 行目标 |

### 13.2 Overall Verdict

**PASS（附非阻塞项）**。无阻塞问题。用户已于 2026-11-21 验收通过；剩余项为实现前补验：

1. Mermaid 图未实际渲染验证。
2. 实现前用 PoC 复验 PydanticAI / FastMCP / DeepSeek 的实际行为。

### 13.3 Blocking Issues

无。

### 13.4 Suggestions

1. 在 GitHub 或 VS Code 中打开 `docs/architecture/`，确认 6 张 Mermaid 图渲染正常。
2. 为外部技术事实增加一个统一的「来源 URL 附录」，避免散落在 Spec。
3. 实现前用 PoC 复验 PydanticAI 2.71、FastMCP、MCP 协议与 DeepSeek 行为。
4. 如认为 `08-data-model.md` 过长，可拆分「数据模型」与「保留/安全策略」两篇，但不影响当前使用。

## 14. Gate

- 本任务已关闭（`Closed`），架构文档可作为实现依据。
- 阶段 2 已启动：M0 实现 Spec 见 `mydocs/specs/2026-11-21_17-51_Reportify-M0-Bootstrap.md`。
- 编码前必须收到该 Spec 的精确批准 `Plan Approved`。
- 可选执行 `ARCHIVE` 沉淀 human/llm 双视角知识。

## 15. Acceptance Record

| 项 | 内容 |
| --- | --- |
| 验收人 | 用户 |
| 日期 | 2026-11-21 |
| 结论 | 验收通过，无修改要求 |
| 证据 | 用户消息「我验收通过了」 |
| 后续 | 进入 M0 实现规划（不直接编码） |
