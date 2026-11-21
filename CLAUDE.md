# CLAUDE.md

> Claude Code 项目入口。完整规则见 [AGENTS.md](AGENTS.md)；两者冲突时以 `AGENTS.md` 与最新 Spec 为准。  
> 最后更新：2026-11-21。

---

## 项目

Reportify：通用型 AI 数据分析与可视化 Agent 平台。当前处于**架构设计 V3 完成、尚未实现**的阶段。

## 必读

1. `docs/architecture/README.md` — 架构索引。
2. `docs/architecture/08-data-model.md` — 字段与实体真相源。
3. `mydocs/specs/` 最新 Spec — 当前任务与恢复锚点。
4. `prompt.md` — 原始需求，**在 §11.2 截断**，§12+ 缺失。

## 工作方式（SDD-RIPER-ONE）

- 先复述目标、任务单元、边界与验证方式。
- 未落盘 Spec，不写业务代码。
- 进入 Execute 前必须收到精确字样 `Plan Approved`。
- 默认单项执行；用户说 `全部` 才批量。
- 偏差、验证结论与用户决策回写 Spec。
- 完成必须有证据；不得自行宣布完成。

## 边界

- 只设计 `prompt.md` §1–§11；§12+ 仅最小接口契约。
- 不做多租户、RBAC、微服务、React/TypeScript。
- LLM 不生成可执行 SQL/Python/JS；数据源默认只读；工具默认拒绝。
- 不启用 MCP stdio；不执行用户脚本。
- 报告只接受 Pydantic 校验后的 Report Schema。

## 技术基线（2026-11-21）

Python 3.12、FastAPI、SQLAlchemy 2.0 async、Pydantic v2、Alembic、uv、PydanticAI v2（2.71.x）、DeepSeek `deepseek-flash` / `deepseek-v4-pro`、Pandas、PostgreSQL、Redis、ARQ、Jinja2、ECharts、MCP Streamable HTTP（FastMCP）、OpenTelemetry。

**禁止**：`deepseek-chat` / `deepseek-reasoner`、PydanticAI V1 类名（`MCPServer*`、`OpenAIModel`）、`Agent(usage_limits=)`、`MCPToolset(tool_filter=/prefix=)`。

## 文档与验证

- 中文正文；标识符英文；每篇架构文档保持固定结构。
- 跨文档字段/事件/状态以 `08-data-model.md` 为准。
- 外部事实注明来源与核查日期；未证实项标 `未确认`。
- 没有测试、日志或用户验收，不得宣布完成。

## 恢复

新会话先读 `docs/architecture/README.md` 与最新 Spec，运行 `git status`，复述目标与下一步。**不要执行 `git clean`。**
