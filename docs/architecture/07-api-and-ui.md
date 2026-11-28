# 07 · API 与管理台

> 依赖：`05-conversation-task.md`、`03-tooling-and-mcp.md`、`06-workspace-skills-templates.md`。  
> 前端约束：Jinja2 + 原生 HTML/CSS/JavaScript，不引入 React / TypeScript / 构建链。

---

## 1. Purpose

定义管理台与后端之间的契约：路由、事件流、错误模型、页面职责。目标是让 8 个视图（既有 5 个 + 配置 3 个）都能由同一套 API 驱动，并保持实现轻量。

---

## 2. Non-Goals

- 不做报告内追问、在线筛选、图表下钻。
- 不做复杂 RBAC；单用户本地模式。
- 不做前端 SPA 路由与状态管理库。
- 不在本阶段实现定时任务配置 UI（§12+）；只展示状态与「立即运行」。

---

## 3. API 约定

| 项 | 约定 |
| --- | --- |
| Base | `/api/v1` |
| 格式 | JSON；时间 ISO 8601 UTC；ID 为 UUID |
| 分页 | 列表用 `limit` + `offset`；消息用 `after_sequence` 游标 |
| 幂等 | 创建 Run 支持 `Idempotency-Key` |
| 版本 | 路径版本；破坏性变更升 `v2` |
| 内容类型 | `application/json`；SSE 为 `text/event-stream` |

### 3.1 错误模型

```json
{
  "type": "https://reportify.local/errors/conversation-busy",
  "title": "Conversation is busy",
  "status": 409,
  "code": "conversation_busy",
  "detail": "该会话已有运行中的任务，请等待或取消。",
  "retryable": false,
  "instance": "/api/v1/conversations/..."
}
```

稳定错误码：`invalid_argument`、`unauthorized`、`forbidden`、`not_found`、`conflict`、`conversation_busy`、`validation_failed`、`rate_limited`、`dependency_unavailable`、`internal_error`。

---

## 4. 认证与安全头

| 项 | MVP |
| --- | --- |
| 绑定地址 | 默认 `127.0.0.1`；对外暴露必须显式配置 |
| 认证 | 可选 `REPORTIFY_AUTH_TOKEN` Bearer；默认本地无认证 |
| CSRF | Cookie 模式使用 SameSite=Lax + CSRF token；Token 模式不依赖 Cookie |
| CSP | `default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'` |
| 缓存 | 敏感接口 `Cache-Control: no-store` |
| 脱敏 | 凭证字段永不返回；错误信息不含连接串 |

---

## 5. 路由组

### 5.1 会话与任务

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/conversations` | 会话列表，按 `last_message_at` |
| POST | `/conversations` | 创建会话 |
| GET | `/conversations/{id}` | 会话详情 |
| PATCH | `/conversations/{id}` | 重命名 / 归档 |
| GET | `/conversations/{id}/messages` | 消息分页（`after_sequence`） |
| POST | `/conversations/{id}/messages` | 写入用户消息，创建/选择 Task，启动 Run |
| GET | `/conversations/{id}/tasks` | 会话内任务列表 |
| GET | `/tasks/{id}` | 任务详情（计划、数据源、报告） |
| POST | `/tasks/{id}/runs` | 在同一任务下启动新 Run |
| GET | `/runs/{id}` | 运行状态与用量 |
| GET | `/runs/{id}/events` | SSE 事件流（支持重放） |
| POST | `/runs/{id}/cancel` | 取消（幂等） |
| GET | `/runs/{id}/approvals` | 待审批工具调用 |
| POST | `/runs/{id}/approvals/{approval_id}` | 允许 / 拒绝 |

> 实现注记（2026-11-22，M5）：§5.1–§5.5 的路由已全部落地。审批接口的 `decision` 取
> `approve`/`deny`；全部待批项决策后同一个 run 续跑（`waiting_approval → running → succeeded`）。
> `/runs/{id}/events` 在 run 处于 `waiting_approval` 时保持连接（不发终态事件）。
> 分析工作台已实现审批卡片：收到 `approval_required` 事件后展示工具名、风险与「批准/拒绝」按钮，
> 提交后调用审批接口并在全部决策后继续执行（§8.1 第 6 步）。

**POST 消息请求体**：

```json
{
  "content": "分析最近 30 天数据趋势",
  "task_id": null,
  "skill_names": ["sales-analysis"],
  "template_name": "executive-report"
}
```

响应：

```json
{ "message_id": "...", "task_id": "...", "run_id": "..." }
```

### 5.2 数据源

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/data-sources` | 列表 / 创建 |
| GET/PATCH/DELETE | `/data-sources/{id}` | 详情 / 更新 / 删除 |
| POST | `/data-sources/{id}/test` | 连接测试 |
| POST | `/data-sources/{id}/sync` | 结构同步 |
| GET | `/data-sources/{id}/tables` | 表列表 |
| GET | `/data-sources/{id}/tables/{table}/columns` | 字段列表 |
| PATCH | `/data-sources/{id}/columns/{column_id}` | 展示名、单位、描述、标签 |
| POST | `/data-sources/{id}/columns/reprofile` | 重新统计 |

### 5.3 MCP

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/mcp/servers` | 列表 / 添加 |
| GET/PATCH/DELETE | `/mcp/servers/{id}` | 详情 / 更新 / 删除 |
| POST | `/mcp/servers/{id}/test` | 连接测试 |
| POST | `/mcp/servers/{id}/discover` | 刷新工具 |
| GET | `/mcp/servers/{id}/tools` | 工具与授权状态 |
| PUT | `/mcp/tools/{tool_id}/grant` | 设置授权与风险等级 |
| DELETE | `/mcp/tools/{tool_id}/grant` | 撤销授权 |
| GET | `/mcp/audits` | 调用审计（按 Server/工具/状态过滤） |

### 5.4 Workspace / Skills / Templates

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/workspace/files` | 文件清单与 hash |
| GET | `/workspace/files/{path}` | 只读查看（大小限制） |
| POST | `/workspace/reload` | 重新扫描 |
| GET | `/workspace/audits` | 加载/拒绝记录 |
| GET | `/skills` | Skill 索引 |
| GET | `/skills/{name}` | Skill 详情与全文 |
| POST | `/skills/{name}/validate` | 校验 frontmatter |
| GET | `/report-templates` | 模板索引 |
| GET | `/report-templates/{name}` | 模板详情 |
| POST | `/report-templates/{name}/validate` | 校验 YAML 与 block |

### 5.5 报告与系统

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/reports` | 报告列表（最小） |
| GET | `/reports/{id}` | 元数据与 lineage |
| GET | `/reports/{id}/download` | 下载 HTML（路径校验） |
| GET | `/health` | 存活 |
| GET | `/ready` | 依赖就绪（PG/Redis） |
| GET | `/config` | 非敏感能力与版本 |

---

## 6. SSE 事件契约

```http
GET /api/v1/runs/{run_id}/events
Accept: text/event-stream
Last-Event-ID: 42
```

```text
id: 43
event: tool_call
data: {"tool_call_id":"...","tool_name":"query_dataset","args_redacted":{...},"status":"started"}

id: 44
event: tool_result
data: {"tool_call_id":"...","status":"succeeded","duration_ms":820,"summary":"..."}
```

规则：

- `id` 为 `run_event.sequence`；客户端断线后带 `Last-Event-ID` 重放。
- 每 15 秒发送注释心跳 `: keep-alive`。
- 终态事件（`run_completed` / `error`）后关闭连接。
- 事件类型与 `run_event.event_type` 一致，不另造协议。
- 审批事件携带 `approval_id`、`tool_name`、`risk`、`args_redacted`；不发送完整结果。

---

## 7. 管理台视图

### 7.1 既有 5 个视图

| 视图 | 关键内容 | 数据来源 |
| --- | --- | --- |
| 分析工作台 | 会话流、Agent 执行过程、产物卡片、输入框 | conversations / messages / runs SSE |
| 报告库 | 报告列表、类型、数据源、样本量、状态、查看/下载 | reports |
| 定时任务 | Cron、启停、上次/下次执行、生成数量 | 只读状态；「立即运行」调用 runs |
| 数据源 | 连接卡片、只读模式、Schema、表、同步 | data-sources |
| 字段元数据 | 类型徽章、展示名、单位、标签、描述 | columns |

### 7.2 新增 3 个配置视图

| 视图 | 关键内容 |
| --- | --- |
| MCP Servers | Server 列表、添加/编辑、测试、工具列表、逐工具授权、审计入口 |
| Skills | 索引、详情、校验、重新加载、引用工具提示 |
| Report Templates | 索引、详情、校验、重新加载、允许的 block 类型 |

### 7.3 页面结构

```text
templates/
├── layout.html              # 侧边栏、顶栏、CSP meta
├── analysis.html            # 分析工作台
├── reports.html             # 报告库
├── scheduler.html           # 定时任务
├── sources.html             # 数据源
├── metadata.html            # 字段元数据
├── mcp.html                 # MCP Servers
├── skills.html              # Skills
└── templates.html           # Report Templates
static/
├── app.css
├── api.js                   # fetch 封装、错误处理
├── stream.js                # EventSource 封装
└── views/*.js               # 每个页面的轻量逻辑
```

> 实现注记（2026-11-22，M4）：以上文件已按此结构落地。页面由 FastAPI 直接返回 Jinja2 骨架
> （`GET /analysis` … `GET /templates`，`/` 302 到 `/analysis`），静态资源挂在 `/static`；
> 数据一律由 `static/views/*.js` 调 API 后用 `textContent` 写入，因此 CSP 可保持
> `script-src 'self'`（无内联脚本、无 `unsafe-eval`）。定时任务视图只做状态说明：创建与调度属于 §12+。

---

## 8. 关键交互

### 8.1 分析工作台

1. 用户输入 → `POST /messages` → 获得 `run_id`。
2. 打开 `EventSource` 订阅 `/runs/{id}/events`。
3. 执行面板按事件追加步骤；工具调用显示名称、耗时、状态。
4. 终态后拉取 `/tasks/{id}` 与报告链接。
5. 用户可随时 `POST /cancel`；按钮变为「已取消」。
6. 写工具需要审批时，弹出审批卡片；提交后继续同一 Run。

### 8.2 数据源配置

1. 填写连接信息 → `POST /test`（不保存也可测试）。
2. 保存 → `POST /data-sources`。
3. `POST /sync` 发现表与字段。
4. 在字段元数据页编辑展示名/单位/标签；标签只影响展示。

### 8.3 MCP 配置

1. 添加 Server → `POST /mcp/servers`。
2. `POST /test`：SSRF 校验 → 连接 → 发现工具。
3. 工具默认无授权；逐个设置风险等级与 grant。
4. 写/破坏性工具显示显式警告。
5. 审计页可按工具查看调用记录。

---

## 9. 前端实现约束

- 无构建步骤：静态文件直接由 FastAPI 挂载。
- 所有动态文本使用 `textContent` 或转义，禁止把不可信内容拼进 `innerHTML`。
- EventSource 只读；写操作走 `fetch`。
- 表单提交使用标准 HTML，JS 渐进增强。
- 响应式布局遵循既有设计 demo 的断点与配色变量。
- 报告页面自带 ECharts 脚本与数据，不依赖管理台运行时。

> 实现注记（2026-11-28，M7）：报告是**单文件 HTML**，内联 ECharts 5.5.0（vendored，Apache-2.0），
> 图表用 `echarts.init` 渲染，并在 `<details>` 里保留表格数据供无脚本环境查看。为支持内联，
> `GET /api/v1/reports/{id}/download` 使用报告专属 CSP（`script-src 'unsafe-inline'`），
> 管理台页面仍保持严格 CSP。报告体积约 1 MB（ECharts 内联所致）。

---

## 10. Failure Modes

| 场景 | 表现 | 处理 |
| --- | --- | --- |
| SSE 断线 | 执行面板停止 | 自动重连并带 `Last-Event-ID`；仍失败则轮询 `/runs/{id}` |
| 会话忙 | 409 | UI 提示等待或取消 |
| 连接测试失败 | 错误卡片 | 展示脱敏原因与建议 |
| 工具授权过期 | 运行中 403 | 事件提示重新授权 |
| 报告文件缺失 | 下载 404 | 展示 lineage 与重新生成入口 |
| 大文件下载 | 内存压力 | 流式响应，限制并发 |

---

## 11. Open Questions

1. 是否需要在 MVP 提供简易登录页，还是仅靠本地绑定 + 可选 Token？
2. 定时任务的创建/编辑 UI 是否在 §12+ 一并设计？
3. MCP 审计页是否需要导出 CSV？
4. 报告库的搜索与筛选需要支持到什么粒度？
