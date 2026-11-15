## 七、多轮对话、报告迭代与记忆管理系统

Reportify 不是一次性报告生成工具，而是一个支持持续对话、反复修改和长期使用的 AI 数据分析 Agent 平台。

用户可能围绕同一份报告连续提出多轮修改意见，也可能在同一个会话中切换不同的分析任务。

系统必须具备完整的会话持久化、任务状态管理、上下文压缩、记忆管理和报告版本控制能力。

核心目标：

**用户不需要每次重新解释之前的分析背景，Agent 能够理解当前任务进度、历史修改意见和用户长期偏好，并在此基础上继续工作。**

### 1. Conversation Management

管理用户与 Agent 的多轮对话。

支持：

- 创建会话。
- 会话列表。
- 历史消息持久化。
- 会话继续。
- 会话重命名。
- 会话归档。
- 会话恢复。
- 不同分析任务之间的关联。

每条消息应记录：

- conversation_id
- role
- content
- message_type
- task_id
- created_at
- metadata

消息类型包括：

- 用户消息。
- Agent 回复。
- Tool Call。
- Tool Result。
- 系统事件。
- 分析计划。
- 报告生成事件。

不能只保存用户和 Agent 的最终文本，还需要保存必要的工具调用过程和执行事件，以便恢复任务和追溯问题。

### 2. Analysis Task Management

Conversation 和 Analysis Task 必须分离。

一个 Conversation 可以包含多个 Analysis Task。

一个 Analysis Task 对应一次相对独立的分析目标，可以拥有多个报告版本。

任务需要记录：

- task_id
- conversation_id
- task_goal
- data_source_refs
- analysis_plan
- execution_status
- current_state
- current_report_version
- created_at
- updated_at

任务状态至少包含：

- CREATED
- PLANNING
- RUNNING
- WAITING_FOR_USER
- COMPLETED
- FAILED
- CANCELLED

需要支持：

- 任务创建。
- 任务执行。
- 任务暂停。
- 任务恢复。
- 任务取消。
- 任务失败恢复。
- 任务状态持久化。

对于长时间执行的任务，不能仅依赖内存中的 Agent 对象保存状态。

### 3. Report Revision Workflow

用户生成报告后，可以通过自然语言不断修改。

例如：

- 不需要这个图表。
- 增加一个地区分布分析。
- 改成和上个月对比。
- 把异常分析放在最前面。
- 结论表达得更简洁。
- 排除退款订单。
- 使用另一种报告模板。

Agent 首先识别反馈类型：

1. 展示调整。
2. 报告结构调整。
3. 分析维度调整。
4. 数据范围调整。
5. 指标计算口径调整。
6. 结论表达调整。

根据反馈类型制定增量修改计划。

原则：

- 仅修改受影响的分析步骤。
- 不需要重新执行的步骤应尽量复用。
- 数据口径发生变化时，必须重新计算受影响的指标。
- 数据范围变化时，需要重新获取对应数据。
- 展示方式变化时，可以只修改 Report Schema 并重新渲染。
- 修改前保留当前报告版本。
- 修改完成后创建新的报告版本。

每个 Report Version 应保存：

- report_id
- version_number
- report_schema
- analysis_task_id
- source_snapshot_refs
- template_version
- revision_description
- created_at

支持报告版本历史、版本比较和回滚。

### 4. Memory Management

设计分层记忆系统，不要把所有记忆简单存储在一个 Memory 表中。

#### L1：Conversation History

完整保存历史消息、工具调用和任务事件。

用途：

- 查看之前的对话。
- 恢复会话。
- 追溯 Agent 的执行过程。

#### L2：Working Memory

保存当前 Analysis Task 的结构化状态。

包括：

- 用户原始目标。
- 当前数据源。
- 当前数据范围。
- 分析计划。
- 已完成步骤。
- 待完成步骤。
- 用户修改意见。
- 当前计算口径。
- 当前报告版本。
- 关键工具结果引用。

Working Memory 应使用结构化 Pydantic Model 定义，并持久化到 PostgreSQL。

它是多轮分析过程中恢复任务状态的主要依据。

不能仅通过总结历史聊天来恢复任务状态。

#### L3：Long-term Memory

保存用户长期稳定的偏好和规则。

例如：

- 默认报告语言。
- 用户喜欢的图表类型。
- 默认报告结构。
- 常用指标口径。
- 常用时间对比方式。
- 用户明确确认的分析习惯。

长期记忆应包含：

- memory_id
- memory_type
- content
- scope
- source
- confidence
- status
- created_at
- updated_at

支持：

- 新增记忆。
- 修改记忆。
- 删除记忆。
- 查看记忆来源。
- 记忆冲突处理。
- 记忆版本记录。

必须区分临时指令和长期偏好。

例如：

"这次报告使用英文"不能自动覆盖用户的默认语言偏好。

"以后所有经营报告都使用中文"可以作为长期偏好候选，但应让用户确认。

不能将所有用户反馈自动写入长期记忆。

#### L4：Knowledge & Skills

保存：

- Skills。
- 数据字典。
- 领域知识。
- 用户参考文档。
- 报告模板。
- 分析规范。

这部分属于可复用的知识和能力，不等同于用户对话记忆。

### 5. Context Management & Compression

必须设计上下文管理机制。

不能无限制地将完整历史消息、工具结果和分析数据传给 LLM。

采用组合式上下文管理：

1. Recent Messages：保留最近的完整消息。
2. Conversation Summary：对较早的历史消息进行摘要。
3. Working Memory：加载当前任务的结构化状态。
4. Long-term Memory Retrieval：按任务检索相关长期记忆。
5. Tool Result References：引用已保存的工具结果，不重复传递大量数据。
6. Context Budget：控制每次 Agent 请求的上下文规模。

上下文压缩触发条件应基于 Token 使用量或上下文预算，而不是固定的对话轮数。

压缩时必须保留：

- 用户原始需求。
- 用户明确确认的修改意见。
- 当前数据口径。
- 分析计划。
- 已完成和未完成步骤。
- 当前报告版本。
- 关键计算结果及其引用。
- 尚未解决的问题。

压缩后的摘要需要具备版本和来源信息。

不能让摘要替代原始消息的持久化存储。

如果摘要遗漏信息，应允许根据原始历史消息重新构建上下文。

对于工具执行结果和大规模数据集，应存储在外部持久化层，只将必要的摘要、统计信息和引用传入上下文。

### 6. Memory Lifecycle

设计记忆的创建、更新和检索机制。

记忆来源包括：

- 用户明确提出的长期偏好。
- 用户确认的指标口径。
- 用户多次重复表达的稳定习惯。
- 用户主动保存的分析规范。

不要把单次临时修改自动升级为长期记忆。

记忆应当能够追溯来源，并允许用户查看、编辑和删除。

不同作用范围的记忆需要隔离：

- 全局用户偏好。
- 工作空间偏好。
- 特定项目规则。
- 当前任务状态。

发生记忆冲突时，优先使用当前任务中用户明确提出的最新指令，同时不能让临时指令永久覆盖长期配置。

### 7. Persistence Architecture

优先使用 PostgreSQL 实现持久化。

建议核心数据表：

- conversations
- messages
- conversation_summaries
- analysis_tasks
- task_states
- task_events
- memories
- memory_revisions
- reports
- report_versions

Redis 负责缓存、任务队列和必要的短期运行态数据。

ARQ 负责异步任务执行。

不能将 Redis 作为唯一的对话历史或长期记忆存储。

暂时不引入独立向量数据库。优先通过 PostgreSQL 结构化查询和关键词检索完成记忆管理，未来有明确的语义检索需求后再评估 pgvector。

### 8. Agent Runtime Integration

Agent 每次接收用户消息时，需要按以下流程构建上下文：

1. 读取 Conversation。
2. 加载当前 Analysis Task。
3. 加载 Working Memory。
4. 加载必要的历史摘要。
5. 检索相关 Long-term Memory。
6. 加载 SOUL.md、USER.md、AGENTS.md。
7. 根据任务匹配 Skills。
8. 选择报告模板。
9. 理解用户当前意图。
10. 制定新任务或增量修改计划。
11. 通过 Tool Registry 执行授权工具。
12. 更新 Working Memory。
13. 生成或修改 Report Schema。
14. 创建报告新版本。
15. 保存消息、事件和执行结果引用。
16. 根据上下文预算决定是否进行摘要压缩。

### 9. 安全和可靠性

- 历史对话不能覆盖系统级安全策略。
- 记忆不能成为绕过工具授权的途径。
- Agent 不能将未经验证的工具结果作为事实。
- 摘要压缩不能删除原始消息。
- 任务恢复必须基于持久化状态。
- 工具调用结果应具备任务关联和执行追溯能力。
- 报告版本不能被静默覆盖。
- 记忆更新需要来源和修改记录。
- 不同工作空间之间的记忆必须隔离。

### 10. 设计目标

最终 Reportify 应该支持完整的持续分析体验：

用户提出需求 → Agent 生成报告 → 用户反馈 → Agent 理解修改意图 → 增量分析 → 生成新版本 → 用户继续反馈。

用户还可以在后续会话中继续之前的分析任务。

系统能够记住用户确认过的长期偏好，加载对应 Skills 和报告模板，不需要用户重复描述相同要求。

整个机制应基于模块化单体设计，不为记忆管理引入不必要的独立服务和复杂 Agent 架构。
