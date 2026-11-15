# Reportify 项目架构设计任务（V3）

## 一、角色定位

你是一名资深 AI Agent 架构师、Python 全栈工程师、数据分析平台架构师。

我准备开发一个名为 Reportify 的开源项目。

你需要从产品设计、系统架构、Agent Runtime、数据处理、MCP 扩展、记忆管理、工程实践等多个维度，协助我完成 Reportify 的整体架构设计。

不要急于编写业务代码。

当前阶段以架构讨论、技术选型、模块边界、数据模型、执行流程和工程方案为主。

所有设计都需要考虑真实生产环境中的可维护性、可靠性、安全性和可扩展性。

不要为了展示技术能力而堆砌技术栈，也不要过度设计。

---

# 二、项目定位

Reportify 是一个**通用型 AI 数据分析与可视化 Agent 平台**。

核心目标：

用户接入自己的数据源，或者通过 MCP 接入外部工具和服务，通过自然语言描述分析需求，由 Agent 自动理解需求、规划分析步骤、选择数据源和工具、执行数据分析，最终生成一份包含可视化图表、统计指标和分析结论的 HTML 报告。

Reportify 不绑定特定业务领域。

只要能够获取相关数据，原则上就应该能够进行通用的数据探索、统计分析、趋势分析、异常检测、对比分析和报告生成。

Reportify 不仅仅是一个一次性的报告生成器，还应该是一个支持持续对话、反复修改、长期记忆和个性化配置的 AI Agent 平台。

用户可以通过持续对话逐步完善分析结果，不需要每次重新解释之前的需求。

## 核心产品理念

1. 用户不需要具备 BI 工具使用经验。
2. 用户不需要预先理解数据库字段的业务含义。
3. Agent 能够通过字段类型、数据分布和统计特征理解数据的基本结构。
4. 用户通过自然语言定义分析需求。
5. Agent 负责理解需求、规划分析过程、选择工具和组织分析结论。
6. Python 负责实际的数据获取、统计计算和结果校验。
7. 最终产物是包含 ECharts 图表和分析结论的静态 HTML 报告。
8. 报告中的指标、图表和分析结论都应该能够追溯到原始数据、查询条件和计算过程。
9. 用户可以自主接入 MCP Server，扩展 Agent 的外部工具能力。
10. 用户可以通过 Skills 定义可复用的分析能力。
11. 用户可以通过配置文件定义 Agent 的角色、行为和长期偏好。
12. 用户可以自定义报告模板，不需要每次重复描述报告结构。
13. Agent 应该能够记住当前分析任务的进度、用户修改意见和历史报告版本。
14. 用户可以通过多轮对话持续修改报告。
15. 系统需要具备完整的会话持久化、记忆管理、上下文压缩和任务恢复能力。

---

# 三、已确认的技术选型与架构约束

以下是目前已经确定的技术基线。除非发现明确的技术问题，否则不要随意更换。

| 维度 | 技术选型 | 说明 |
| --- | --- | --- |
| Python | Python 3.12+ | 后端主要开发语言 |
| Web 框架 | FastAPI | API 服务 |
| ORM | SQLAlchemy 2.0 | 数据库访问 |
| 数据校验 | Pydantic v2 | Schema 和数据校验 |
| 数据库迁移 | Alembic | 数据库版本管理 |
| 包管理 | uv | Python 依赖管理 |
| Agent 框架 | PydanticAI | Agent Runtime |
| LLM | DeepSeek API | 通过 OpenAI 兼容接口接入 |
| 数据处理 | Pandas | MVP 数据分析 |
| 元数据数据库 | PostgreSQL | 系统元数据和分析数据 |
| 缓存 | Redis | 缓存和短期运行态数据 |
| 异步任务 | ARQ | 后台任务和定时任务 |
| 报告模板 | Jinja2 | HTML 渲染 |
| 图表 | ECharts | 报告可视化 |
| 可观测性 | Langfuse 或 OpenTelemetry | Agent 和工具执行追踪 |
| MCP | MCP Python SDK / PydanticAI 集成 | 外部工具接入 |

## 3.1 Agent 框架

采用 PydanticAI。

暂时不使用 LangGraph。

不引入 Pi Agent + Node.js 双语言架构。

不为了记忆管理单独引入复杂的 Agent 框架。

需要充分研究 PydanticAI 的：

- Agent 生命周期。
- Tool Calling。
- 结构化输出。
- Dependency Injection。
- Dynamic Toolset。
- MCPToolset。
- 上下文管理。
- 多轮对话。
- Usage Limits。
- 工具执行生命周期。
- 错误处理和重试。

需要结合 PydanticAI 的真实 API 设计，不要根据过时版本或想象编写实现方案。

## 3.2 LLM

使用 DeepSeek API，通过 OpenAI 兼容接口接入。

MVP 阶段不设计复杂的多模型抽象层。

需要实际验证：

- Tool Calling。
- 多步骤工具调用。
- 结构化输出。
- 参数 Schema 兼容性。
- 长上下文处理。
- 工具调用失败时的降级策略。

DeepSeek 不需要直接理解 MCP 协议。

由 PydanticAI 和 MCP Client 将 MCP Tools 转换为 Agent 可以调用的工具。

## 3.3 数据处理

MVP 使用 Pandas。

数据规模目标小于 100 万行。

暂不引入 Polars 和 DuckDB。

分析引擎需要保持接口抽象，方便未来切换计算引擎。

## 3.4 部署形态

采用模块化单体架构。

单机、本地优先。

面向个人开发者和小团队使用。

不需要多租户、复杂 RBAC 和微服务架构。

需要支持 Docker 部署。

## 3.5 前端

不使用 React、TypeScript、Vite、pnpm。

管理界面优先采用轻量 HTML、CSS、JavaScript。

通过 FastAPI 提供服务端 API。

不为了简单的管理页面引入复杂前端工程体系。

## 3.6 报告约束

最终报告是静态 HTML。

使用 Jinja2 + ECharts。

支持：

- KPI 卡片。
- 折线图。
- 柱状图。
- 饼图。
- 散点图。
- 数据表格。
- 分析结论。
- 数据来源。
- 计算口径。
- ECharts 基础交互。

不支持在线筛选、下钻和报告内追问。

LLM 只能输出经过 Pydantic 校验的结构化 Report Schema。

禁止 LLM 直接生成 HTML、React 组件或可执行 JavaScript。

---

# 四、整体产品架构

Reportify 计划包含以下核心模块：

1. Data Connector：数据源接入。
2. MCP Hub：外部 MCP Server 管理。
3. MCP Client Runtime：MCP 协议通信和工具执行。
4. Tool Registry：统一工具管理。
5. Agent Workspace：Agent 配置文件和个性化设置。
6. Skills Manager：可复用分析能力管理。
7. Conversation Management：多轮对话管理。
8. Memory Management：记忆管理。
9. Context Management：上下文构建和压缩。
10. Analysis Task Management：分析任务管理。
11. Agent Runtime：Agent 执行引擎。
12. Data Profiling：数据画像。
13. Analysis Engine：确定性数据分析。
14. Report Engine：结构化报告生成。
15. Report Revision：报告迭代和版本管理。
16. Scheduler：定时报告和异步任务。
17. Observability：执行追踪和监控。

采用模块化单体架构，各模块职责清晰，避免业务逻辑相互耦合。

---

# 五、Data Connector：数据源接入

负责结构化数据源的接入。

MVP 只实现 PostgreSQL Connector。

后续考虑：

- MySQL。
- CSV。
- Excel。
- REST API。
- 其他结构化数据源。

核心职责：

- 数据源连接管理。
- 连接配置和凭证管理。
- 数据库结构发现。
- 表结构发现。
- 字段类型识别。
- 安全查询。
- 分页读取。
- 查询超时控制。
- 错误处理。
- 数据快照和来源追溯。

Data Connector 负责数据获取，不承担 Agent 工具协议管理。

需要明确 Data Connector 和 MCP 的边界。

MCP 是外部工具能力接入协议，Data Connector 是 Reportify 自身的数据访问抽象。

两者可以协作，但不能混为一谈。

---

# 六、MCP Hub：用户自主接入外部工具

这是 Reportify 长期扩展能力的重要组成部分。

Reportify 不应该在服务端硬编码 GitHub、Jira、Sentry 等第三方 MCP Server。

用户应该能够通过前端界面自主添加 MCP Server。

## 6.1 MCP 管理中心

用户可以：

- 添加 MCP Server。
- 修改 MCP Server 配置。
- 删除 MCP Server。
- 测试连接。
- 启用和禁用连接。
- 查看连接状态。
- 查看 Server 暴露的 Tools。
- 查看工具描述和参数 Schema。
- 选择允许 Agent 使用的工具。
- 修改工具授权。
- 查看工具调用记录。

添加 MCP Server 时支持配置：

- 服务名称。
- 传输协议。
- Server URL。
- 认证方式。
- Access Token。
- OAuth 配置。
- 其他必要的连接参数。

优先支持 Streamable HTTP。

stdio 可以作为后续扩展能力，但必须限制可执行程序、参数、环境变量和工作目录，不能允许任意命令执行。

对于 OAuth、旧版 SSE 等能力，需要根据实际 MCP SDK 支持情况决定实施阶段。

## 6.2 MCP Client Runtime

负责：

- 创建 MCP Client。
- 建立协议连接。
- 完成初始化握手。
- 获取 Server 能力。
- 发现 Tools。
- 调用 Tools。
- 管理连接生命周期。
- 超时处理。
- 异常处理。
- 重试。
- 连接资源释放。
- 工具调用审计。

优先使用官方 MCP SDK 和 PydanticAI 的 MCP 集成。

不要从零实现 MCP 协议。

## 6.3 Tool Registry

统一管理 Reportify 中的所有工具。

工具来源包括：

1. Reportify 内置工具。
2. Data Connector 工具。
3. 用户接入的 MCP Tools。

统一管理：

- 工具标识。
- 工具名称。
- 工具描述。
- 参数 Schema。
- 工具来源。
- 所属连接。
- 启用状态。
- 用户授权状态。
- 权限策略。
- 执行器。

Agent 不直接管理 MCP Server 连接。

Agent 通过 Tool Registry 获取当前任务允许使用的工具。

## 6.4 MCP 工具授权

不采用连接即全权授权的模式。

推荐流程：

1. 用户添加 MCP Server。
2. 系统自动发现工具。
3. 用户查看工具详情。
4. 用户选择允许 Agent 使用的工具。
5. Agent 根据任务动态选择相关工具。
6. 实际执行时再次验证权限。

MCP 协议本身不保证工具具有可靠的只读或写入语义。

不能仅通过工具名称或描述自动认定其权限等级。

需要由 Reportify 提供权限配置策略。

默认只读。

写入操作需要明确授权。

具有破坏性的操作需要额外确认。

## 6.5 MCP 安全

必须考虑：

- 凭证加密存储。
- Token 过期和刷新。
- SSRF 防护。
- 内网地址访问限制。
- 工具执行超时。
- 工具返回大小限制。
- 工具调用次数限制。
- 不可信工具输出处理。
- 权限二次校验。
- 敏感参数脱敏。
- 调用审计。
- Server 异常和连接中断。
- 工具 Schema 变化后的缓存失效。

工具清单是可以刷新的缓存，不能作为连接真实状态的唯一依据。

---

# 七、Agent Workspace：个性化配置系统

Reportify 不应该每次都从零开始理解用户。

用户可以通过文件化配置定义 Agent 的角色、行为规范和长期偏好。

建议提供独立的 Agent Workspace。

初步目录结构：

```text
workspace/
├── AGENTS.md
├── SOUL.md
├── USER.md
├── skills/
│   ├── sales-analysis/
│   │   ├── SKILL.md
│   │   └── references/
│   ├── code-analysis/
│   │   └── SKILL.md
│   └── financial-analysis/
│       └── SKILL.md
└── report-templates/
    ├── default.yaml
    ├── executive-report.yaml
    └── weekly-report.yaml
```

以上是逻辑结构，实际是否需要拆分目录和文件，可以在设计阶段进一步优化。

## 7.1 SOUL.md

定义 Agent 的角色和基本行为。

例如：

- 你是一个专业的数据分析助手。
- 优先使用数据支持结论。
- 不得编造不存在的指标。
- 不确定的数据必须明确说明。
- 表达应该简洁易懂。
- 不得将推测当作事实。

## 7.2 USER.md

保存用户长期偏好。

例如：

- 默认使用中文。
- 报告优先展示核心 KPI。
- 趋势分析默认与上一周期对比。
- 图表优先使用折线图和柱状图。
- 分析结论尽量简洁。

## 7.3 AGENTS.md

定义工作空间级的 Agent 执行规范。

例如：

- 数据分析必须通过 Python 工具完成。
- 所有指标必须有计算口径。
- 报告必须包含数据来源。
- MCP 工具调用必须经过授权检查。
- 不允许执行未授权的写入操作。

需要明确不同配置文件的职责，避免重复定义。

这些用户配置不能覆盖系统级安全策略。

---

# 八、Skills：可复用分析能力

引入类似 Agent Skills 的设计。

Skill 是独立的能力包，用于指导 Agent 如何完成特定任务。

例如：

- 销售分析。
- 财务分析。
- 研发效能分析。
- 代码质量分析。
- 用户行为分析。
- 数据质量分析。

一个 Skill 可以包含：

```text
sales-analysis/
├── SKILL.md
├── references/
└── scripts/
```

SKILL.md 包含：

- Skill 名称。
- Skill 描述。
- 适用场景。
- 分析步骤。
- 分析规则。
- 工具使用建议。
- 输出要求。

## 8.1 Skill 加载

采用渐进式加载：

1. Agent 初始化时读取 Skill 名称和描述。
2. 根据用户任务匹配相关 Skill。
3. 仅加载匹配 Skill 的完整内容。
4. 根据 Skill 指令制定分析计划。
5. 通过 Tool Registry 获取授权工具。
6. 执行分析任务。

不能把所有 Skill 的完整内容一次性塞入 LLM 上下文。

支持用户主动指定 Skill，也支持 Agent 自动匹配。

## 8.2 Skill 安全

Skill 是指导 Agent 工作的配置，不是权限本身。

Skill 不能：

- 绕过 Tool Registry。
- 获取未授权 MCP 工具。
- 覆盖系统级安全规则。
- 自动执行未经授权的操作。

脚本执行需要独立的安全机制和沙箱。

---

# 九、Report Template：自定义报告模板

支持用户创建、编辑、导入和管理报告模板。

模板负责报告结构和展示规范。

例如经营分析报告：

1. 经营概览。
2. 核心 KPI。
3. 趋势分析。
4. 异常数据。
5. 总结和建议。

模板配置可以包括：

- 模板名称。
- 适用场景。
- 报告章节。
- KPI 展示规则。
- 图表类型偏好。
- 报告主题。
- 语言。
- 输出规范。

用户配置一次后，后续只需要提出分析需求，Agent 就可以根据任务自动选择模板。

模板最终必须映射到统一 Report Schema。

Jinja2 负责渲染 HTML。

不允许模板绕过 Report Schema 直接执行任意 HTML 或 JavaScript。

需要明确 Skills 与 Report Template 的区别：

- Skill 决定如何分析。
- Report Template 决定如何呈现。

两者独立管理，但可以组合使用。

---

# 十、Agent Runtime：核心执行引擎

Agent Runtime 是 Reportify 的核心。

它负责组织一次完整的分析任务。

核心职责：

- 接收用户请求。
- 获取会话上下文。
- 加载任务状态。
- 检索长期记忆。
- 加载用户配置。
- 匹配 Skills。
- 选择报告模板。
- 制定分析计划。
- 选择内部工具和 MCP Tools。
- 执行工具调用。
- 整理工具结果。
- 调用分析引擎。
- 生成 Report Schema。
- 保存执行状态。

## 10.1 Agent 工具分类

内部数据工具：

- inspect_dataset
- profile_dataset
- query_dataset
- fetch_dataset

通用分析工具：

- analyze_trend
- analyze_distribution
- compare_periods
- detect_anomalies
- analyze_correlation

MCP Tools：

由用户接入的 MCP Server 动态发现。

报告工具：

- generate_report

不要把所有分析逻辑写进 Prompt。

确定性的数据计算必须由 Python 完成。

## 10.2 Agent 执行原则

LLM 负责：

- 理解需求。
- 规划任务。
- 选择工具。
- 判断下一步行动。
- 解释结果。
- 组织报告。

Python 负责：

- 数据获取。
- 数据清洗。
- 统计计算。
- 指标计算。
- 数据校验。
- 报告数据结构校验。

禁止 LLM 直接生成 SQL、Python 或 JavaScript 并未经验证直接执行。

如果确实需要动态查询，必须通过受限查询构造器或安全 SQL 执行层完成。

## 10.3 Agent 执行控制

需要考虑：

- 最大工具调用次数。
- 最大执行时间。
- Token 使用限制。
- 工具调用失败重试。
- Agent 循环检测。
- 任务取消。
- 任务超时。
- 执行状态持久化。
- 错误恢复。

不要让 Agent 无限制地反复调用工具。

---

# 十一、Conversation Management：多轮对话管理

Reportify 是持续对话产品。

用户可能围绕同一份报告进行多轮修改，也可能在同一个会话中创建多个分析任务。

因此 Conversation 和 Analysis Task 必须分离。

## 11.1 Conversation

负责：

- 创建会话。
- 会话列表。
- 历史消息持久化。
- 会话继续。
- 会话重命名。
- 会话归档。
- 会话恢复。

每条消息需要记录：

- conversation_id。
- role。
- content。
- message_type。
- task_id。
- metadata。
- created_at。

消息类型包括：

- User Message。
- Assistant Message。
- Tool Call。
- Tool Result。
- System Event。
- Analysis Plan。
- Report Event。

需要保存必要的工具调用过程和执行事件，而不是只保存最终文本。

## 11.2 Analysis Task

一个 Conversation 可以包含多个 Analysis Task。

例如：

用户在同一个会话中先分析销售数据，再分析客户留存，之后又回到之前的销售报告进行修改。

Analysis Task 需要记录：

- task_id。
- conversation_id。
- task_goal。
- data_source_refs。
- analysis_plan。
- execution_status。
- current
