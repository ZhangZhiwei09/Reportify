# Reportify

通用型 AI 数据分析与可视化 Agent 平台。M0–M8 已实现：数据层、Agent Runtime、MCP、Workspace/Skills/Templates、
分析引擎、单文件 ECharts 报告与定时任务（Cron + 进程内 tick）。

## 快速开始

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d
uv sync
uv run alembic upgrade head
uv run uvicorn reportify.main:app --reload
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/api/v1/ready
```

## 验证

```bash
uv run ruff check .
uv run pytest
```

## 文档

- 架构设计：[`docs/architecture/README.md`](docs/architecture/README.md)
- 当前任务与恢复锚点：[`mydocs/specs/`](mydocs/specs/)
- 项目规则：[`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md)
