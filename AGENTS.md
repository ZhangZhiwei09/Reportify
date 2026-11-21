# AGENTS.md

> Reportify 项目级 Agent 规则。所有会话开始前先读本文件，再读活跃 Spec。  
> 最后更新：2026-11-21。

---

## 1. 项目是什么

Reportify 是一个通用型 AI 数据分析与可视化 Agent 平台：接入数据源或 MCP 工具，用自然语言提出分析需求，Agent 规划并调用工具，Python 完成确定性计算，最终生成带 ECharts 图表、指标口径与数据来源的静态 HTML 报告。

当前阶段：**架构设计 V3 已完成，尚未开始实现。**

---

## 2. 权威来源与阅读顺序

1. `docs/architecture/README.md`：架构索引与阅读顺序。
2. `docs/architecture/08-data-model.md`：实体与字段的真相源。
3. `mydocs/specs/` 下最新 Spec：当前任务、决策、进度与恢复锚点。
4. `prompt.md`：原始需求；**注意在 §11.2 处截断**，§12+ 未提供。
5. `docs/reportify-design-demos/`：管理台与报告的视觉基线。

冲突时以 Spec 为准；Spec 与架构文档冲突时，先修正 Spec，再同步架构文档。

---

## 3. 研发流程（SDD-RIPER-ONE）

- 默认使用 `sdd-riper-one` 技能。
- 主流程：`Research → (Innovate) → Plan → Execute → Review`。
- **No Spec, No Code**：未形成并落盘 Spec 前，不写业务代码。
- **Restate First**：先复述最终目标、当前任务单元、边界与验证方式。
- **Checkpoint Before Execute**：执行前展示目标、阶段、批准状态、风险与下一步。
- **No Approval, No Execute**：必须收到精确字样 `Plan Approved` 才能进入 Execute。
- **Done by Evidence**：完成由测试、日志、文件或用户验收证明。
- **Reverse Sync**：实现偏差、验证结论与用户决策必须回写 Spec。

默认单项执行；用户明确说 `全部` / `all` / `execute all` 时才批量执行。

---

## 4. 当前阶段边界

**已完成**：`docs/architecture/` 下的 V3 设计文档（§1–§11 范围）与项目规则文件。

**下一步**：为具体实现模块新建 Spec，经批准后编码。不要在未批准的情况下直接开始实现。

**范围约束**：

- 只设计 `prompt.md` §1–§11；§12+（Memory、Context 压缩、Data Profiling、Analysis Engine、Report Engine、Report Revision、Scheduler）只保留最小接口契约。
- 不做多租户、RBAC、微服务、React/TypeScript 构建链。
- 不允许 LLM 直接生成 SQL、Python、JavaScript 并执行。
- 不允许任意命令执行；MVP 不启用 MCP stdio。
- 数据源默认只读；工具默认拒绝，写操作需显式授权与审批。

---

## 5. 技术基线（核查日期 2026-11-21）

| 维度 | 选择 |
| --- | --- |
| Python | 3.12+ |
| Web | FastAPI |
| ORM / 迁移 | SQLAlchemy 2.0 async / Alembic |
| 校验 | Pydantic v2 |
| 包管理 | uv |
| Agent | PydanticAI **v2**（2.71.x） |
| LLM | DeepSeek `deepseek-flash` / `deepseek-v4-pro` |
| 数据 | Pandas |
| 元数据 | PostgreSQL |
| 缓存/队列 | Redis / ARQ |
| 报告 | Jinja2 + ECharts |
| MCP | Streamable HTTP；PydanticAI `MCPToolset`（FastMCP） |
| 可观测 | OpenTelemetry |

**禁止使用已失效的名称**：

- `deepseek-chat` / `deepseek-reasoner`（2026-07-24 下线）。
- PydanticAI V1 的 `MCPServerStdio` / `MCPServerSSE` / `MCPServerStreamableHTTP` / `OpenAIModel`。
- `Agent(usage_limits=...)`、`Agent(output_retries=...)`、`MCPToolset(tool_filter=/prefix=)`。

实现前按 `docs/architecture/` 中记录的官方来源复验；版本升级需跑契约测试。

---

## 6. 架构硬约束

1. LLM 只做理解、规划、选工具、解释；统计与取数必须由 Python 完成。
2. 报告只接受经 Pydantic 校验的 Report Schema；禁止 LLM 生成 HTML/JS。
3. 每个指标与图表必须可追溯到 SQL/工具、参数、范围、样本量与计算口径。
4. 工具权限三层：请求前过滤、写操作审批、执行前二次校验。
5. MCP 工具默认 `write`，不得根据名称或描述自动认定只读；annotations 不可信。
6. 凭证只存加密的 `secret` 表；日志、审计、API 不出现明文。
7. SSRF 校验必须覆盖 MCP URL 与 OAuth 发现链路的每个 URL。
8. Workspace 文件、Skill、Template 都不能覆盖平台安全策略。

---

## 7. 文档规范

- 正文中文；代码、接口名、字段名、路径用英文。
- 每篇架构文档保持固定结构：`Purpose` / `Non-Goals` / `Responsibilities` / `Interfaces` / `Data & State` / `Key Flows` / `Failure Modes` / `Security Notes` / `Open Questions`。
- 跨文档字段、事件、状态命名以 `08-data-model.md` 为准。
- 外部技术事实注明来源与核查日期；未证实项标 `未确认` 或 `待 PoC`。
- 范围外内容明确标注 `Out of scope`，不要静默扩展。

---

## 8. 验证要求

| 变更类型 | 必须验证 |
| --- | --- |
| 架构文档 | Markdown 结构、Mermaid 渲染、跨文档引用一致 |
| 数据模型 | 迁移脚本、约束、索引、仓库测试 |
| Runtime | 工具循环、取消、超时、预算、事件持久化测试 |
| MCP | Fake Server 上的发现、调用、拒绝、超时 |
| 安全模块 | 负面用例：SSRF、越权、注入、脱敏 |
| API/UI | 错误模型、SSE 重放、XSS 转义 |

没有证据不得宣布完成。

---

## 9. 恢复锚点

新会话或上下文丢失时：

1. 读 `docs/architecture/README.md`。
2. 读 `mydocs/specs/` 最新文件的状态、Plan、Execute Log 与 Checkpoint。
3. 运行 `git status` 确认工作区；不要执行 `git clean`。
4. 复述目标、当前阶段与下一步，再等待指令。
