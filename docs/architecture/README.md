# Reportify 架构文档（V3）

> 状态：设计中（2026-11-21）。本目录只包含设计，不包含业务代码。  
> 范围：`prompt.md` §1–§11；§12+ 模块仅保留最小接口契约。

---

## 1. 这是什么

Reportify 是一个通用型 AI 数据分析与可视化 Agent 平台：用户接入数据源或 MCP 工具，用自然语言提出分析需求，Agent 规划并调用工具，Python 完成确定性计算，最终生成带 ECharts 图表、指标口径与数据来源的静态 HTML 报告。

本目录回答四个问题：

1. 模块怎么分，边界在哪（`01`）。
2. Agent 怎么跑，工具怎么授权（`02`、`03`）。
3. 数据怎么取、会话与任务怎么存（`04`、`05`、`08`）。
4. 配置、界面与工程怎么落地（`06`、`07`、`09`）。

---

## 2. 阅读顺序

| 顺序 | 文档 | 适合谁 |
| --- | --- | --- |
| 1 | [01-system-overview.md](01-system-overview.md) | 所有人；先建立全局图 |
| 2 | [08-data-model.md](08-data-model.md) | 后端；实体与字段的真相源 |
| 3 | [02-agent-runtime.md](02-agent-runtime.md) | Agent/后端；核心执行链路 |
| 4 | [03-tooling-and-mcp.md](03-tooling-and-mcp.md) | Agent/安全；工具与 MCP |
| 5 | [04-data-layer.md](04-data-layer.md) | 数据/后端；连接器与分析契约 |
| 6 | [05-conversation-task.md](05-conversation-task.md) | 后端/产品；多轮与任务 |
| 7 | [06-workspace-skills-templates.md](06-workspace-skills-templates.md) | 产品/Agent；配置与能力包 |
| 8 | [07-api-and-ui.md](07-api-and-ui.md) | 前端/后端；接口与页面 |
| 9 | [09-engineering.md](09-engineering.md) | 工程；目录、测试、部署 |

---

## 3. 文档清单

| 文档 | 内容 |
| --- | --- |
| `01-system-overview.md` | 17 模块范围、容器拓扑、依赖规则、端到端流程、MVP 边界 |
| `02-agent-runtime.md` | PydanticAI V2 映射、run 生命周期、上下文、限制、事件、错误 |
| `03-tooling-and-mcp.md` | Tool Registry、内置工具契约、MCP Hub/Runtime、授权、审计、安全 |
| `04-data-layer.md` | Data Connector 抽象、PostgreSQL 约束、Profiling/Analysis 最小契约 |
| `05-conversation-task.md` | Conversation/Message/AnalysisTask、多任务、恢复 |
| `06-workspace-skills-templates.md` | SOUL/USER/AGENTS、Skills、Report Template |
| `07-api-and-ui.md` | FastAPI 路由、SSE 事件、管理台视图 |
| `08-data-model.md` | 实体、字段、ER、索引、保留策略 |
| `09-engineering.md` | 目录、依赖、配置、测试、Docker、里程碑 |

---

## 4. 已确认的技术基线

| 维度 | 选择 |
| --- | --- |
| Python | 3.12+ |
| Web | FastAPI |
| ORM / 迁移 | SQLAlchemy 2.0 / Alembic |
| 校验 | Pydantic v2 |
| 包管理 | uv |
| Agent | PydanticAI **v2**（核查版本 2.71.0） |
| LLM | DeepSeek（`deepseek-flash` / `deepseek-v4-pro`，通过 OpenAI 兼容接口） |
| 数据 | Pandas（≤100 万行） |
| 元数据库 | PostgreSQL |
| 缓存/队列 | Redis / ARQ |
| 报告 | Jinja2 + ECharts（静态 HTML） |
| MCP | Streamable HTTP；PydanticAI `MCPToolset`（FastMCP） |
| 可观测 | OpenTelemetry（Langfuse 通过 OTLP 可选） |

**注意**：`deepseek-chat` / `deepseek-reasoner` 已于 2026-07-24 下线；PydanticAI V1 的 `MCPServer*`、`OpenAIModel` 等类名在 V2 已删除。

---

## 5. 关键决策（ADR 摘要）

| ID | 决策 | 结论 |
| --- | --- | --- |
| D-01 | 交互式执行 | FastAPI 内异步执行 + SSE；ARQ 只跑定时/长任务 |
| D-02 | Agent 编排 | 单 Agent + 工具循环；计划结构化记录，不强制两阶段 |
| D-03 | 工具授权 | 过滤工具集 + 写操作审批 + 执行前二次校验 |
| D-04 | MCP 连接 | Agent 面 per-run 懒连接；管理面短连接 |
| D-05 | 会话持久化 | 应用消息表 + PydanticAI 历史 JSON |
| D-06 | Workspace | 文件为源；DB 只存索引与审计 |
| D-07 | 报告 | 只定义 Template → Report Schema 与 lineage；渲染器 §12+ |

---

## 6. 范围声明

**已设计**：Data Connector、MCP Hub、MCP Client Runtime、Tool Registry、Agent Workspace、Skills、Report Template、Agent Runtime、Conversation / Analysis Task，以及数据模型与工程方案。

**仅接口**：Memory、Context 压缩、Data Profiling、Analysis Engine、Report Engine、Report Revision、Scheduler。

**明确不做**：多租户、RBAC、微服务、React 前端、LLM 直接生成 HTML/SQL/JS、脚本沙箱。

---

## 7. 术语表

| 术语 | 含义 |
| --- | --- |
| Run | 一次 Agent 执行，对应 `task_run` |
| Task | 一个分析目标，可包含多次 Run，对应 `analysis_task` |
| Tool | 可被 Agent 调用的函数，来源为内置或 MCP |
| Grant | 工具授权记录，默认拒绝 |
| Workspace | 存放 SOUL/USER/AGENTS/Skills/Templates 的目录 |
| Skill | 指导分析方法的配置包，不是权限 |
| Template | 报告结构与展示规范，不是分析逻辑 |
| Lineage | 指标/图表的来源、参数、口径、样本量 |
| Snapshot | 一次查询的条件与范围记录，不含原始数据 |

---

## 8. 如何修改设计

1. 先在 `mydocs/specs/` 更新当前 Spec，写明原因、影响文档与验收方式。
2. 修改对应文档，保持字段名、事件名、状态名与 `08-data-model.md` 一致。
3. 涉及跨文档结论时，在受影响的文档中同步更新，不只改一处。
4. 重大决策新增 ADR 记录，不删除历史结论。
