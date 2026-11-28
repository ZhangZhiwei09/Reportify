"""Tool Registry: registration, filtering and authorization (03 §4).

M2 registers the builtin tools and enforces the default-deny rule. MCP tools join
the same table in M3; nothing here assumes their existence.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.db.models import MCPServer, ToolDefinition, ToolGrant
from reportify.db.repositories import tools as tools_repo
from reportify.modules.tools.naming import mcp_model_name
from reportify.modules.tools.schemas import (
    AuthorizationDecision,
    ToolSpec,
)

logger = logging.getLogger(__name__)

BUILTIN_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="builtin.inspect_dataset",
        model_name="inspect_dataset",
        kind="builtin_data",
        risk_level="read",
        display_name="查看数据结构",
        description=(
            "列出数据源的表与字段（只读）。可传 schema 或 table 缩小范围。"
            "返回表名、字段名、类型、是否可空与行数估计。"
        ),
        arguments={
            "data_source_id": "string",
            "schema": "string",
            "table": "string",
        },
        required_arguments=("data_source_id",),
    ),
    ToolSpec(
        name="builtin.profile_dataset",
        model_name="profile_dataset",
        kind="builtin_data",
        risk_level="read",
        display_name="字段画像",
        description=(
            "对表采样并计算字段统计：空值率、唯一值数、min/max/mean/std、Top 值。"
            "只做统计，不推断业务语义。"
        ),
        arguments={
            "data_source_id": "string",
            "table": "string",
            "columns": "array",
            "sample_size": "integer",
        },
        required_arguments=("data_source_id", "table"),
    ),
    ToolSpec(
        name="builtin.query_dataset",
        model_name="query_dataset",
        kind="builtin_data",
        risk_level="read",
        display_name="受限查询",
        description=(
            "用结构化 QuerySpec 做只读查询（不支持原始 SQL）。返回结果预览、"
            "行数、lineage 与 snapshot_id；完整结果留在服务端。"
        ),
        arguments={
            "data_source_id": "string",
            "spec": "object",
            "preview_rows": "integer",
        },
        required_arguments=("data_source_id", "spec"),
    ),
    ToolSpec(
        name="builtin.fetch_dataset",
        model_name="fetch_dataset",
        kind="builtin_data",
        risk_level="read",
        display_name="分页读取",
        description="按 snapshot_id 分页读取上次查询结果，用于翻页或补充样本。",
        arguments={
            "snapshot_id": "string",
            "offset": "integer",
            "limit": "integer",
        },
        required_arguments=("snapshot_id",),
    ),
    ToolSpec(
        name="builtin.load_skill",
        model_name="load_skill",
        kind="meta",
        risk_level="read",
        display_name="加载 Skill",
        description="按名称加载工作区 Skill 的完整说明，用于遵循特定分析方法。",
        arguments={"name": "string"},
        required_arguments=("name",),
    ),
    ToolSpec(
        name="builtin.generate_report",
        model_name="generate_report",
        kind="report",
        risk_level="write",
        display_name="生成报告",
        description=(
            "提交经校验的 ReportSchema 生成单文件静态 HTML 报告（内联 ECharts）。"
            "每个 run 只能调用一次；指标必须引用已有的 dataset_snapshot。"
        ),
        arguments={"report": "object"},
        required_arguments=("report",),
    ),
    ToolSpec(
        name="builtin.analyze_trend",
        model_name="analyze_trend",
        kind="builtin_analysis",
        risk_level="read",
        display_name="趋势分析",
        description=(
            "按小时/日/周/月聚合指标，返回首末值、变化率、最小二乘斜率与波动率。"
            "只做统计，不解释业务原因；可在口径中看到样本量与分桶方式。"
        ),
        arguments={
            "data_source_id": "string",
            "table": "string",
            "metric": "string",
            "time_column": "string",
            "granularity": "string",
            "agg": "string",
            "start": "string",
            "end": "string",
        },
        required_arguments=("data_source_id", "table", "metric", "time_column"),
    ),
    ToolSpec(
        name="builtin.analyze_distribution",
        model_name="analyze_distribution",
        kind="builtin_analysis",
        risk_level="read",
        display_name="分布分析",
        description=(
            "对字段做直方图与描述统计（均值、标准差、最小值、最大值、偏度、空值率）；"
            "非数值字段返回 Top 频次。"
        ),
        arguments={
            "data_source_id": "string",
            "table": "string",
            "field": "string",
            "bins": "integer",
        },
        required_arguments=("data_source_id", "table", "field"),
    ),
    ToolSpec(
        name="builtin.compare_periods",
        model_name="compare_periods",
        kind="builtin_analysis",
        risk_level="read",
        display_name="周期对比",
        description="比较指标在两个时间区间上的聚合值，返回绝对差与变化率。",
        arguments={
            "data_source_id": "string",
            "table": "string",
            "metric": "string",
            "time_column": "string",
            "current_start": "string",
            "current_end": "string",
            "previous_start": "string",
            "previous_end": "string",
            "agg": "string",
        },
        required_arguments=(
            "data_source_id",
            "table",
            "metric",
            "time_column",
            "current_start",
            "current_end",
            "previous_start",
            "previous_end",
        ),
    ),
    ToolSpec(
        name="builtin.detect_anomalies",
        model_name="detect_anomalies",
        kind="builtin_analysis",
        risk_level="read",
        display_name="异常检测",
        description=(
            "按时间排序后用 z-score 或 IQR 判定异常点，返回异常点、分值与阈值参数。"
            "不推断原因，只报告统计意义上的离群值。"
        ),
        arguments={
            "data_source_id": "string",
            "table": "string",
            "metric": "string",
            "time_column": "string",
            "method": "string",
            "threshold": "number",
        },
        required_arguments=("data_source_id", "table", "metric", "time_column"),
    ),
    ToolSpec(
        name="builtin.analyze_correlation",
        model_name="analyze_correlation",
        kind="builtin_analysis",
        risk_level="read",
        display_name="相关性分析",
        description=(
            "计算多个数值字段的 Pearson 或 Spearman 相关系数矩阵，并返回最强的字段对。"
            "相关不等于因果，结论需说明这一点。"
        ),
        arguments={
            "data_source_id": "string",
            "table": "string",
            "fields": "array",
            "method": "string",
        },
        required_arguments=("data_source_id", "table", "fields"),
    ),
)

_SPECS_BY_MODEL_NAME: dict[str, ToolSpec] = {spec.model_name: spec for spec in BUILTIN_SPECS}
_SPECS_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in BUILTIN_SPECS}

_SCOPE_PRIORITY = {"task": 0, "conversation": 1, "global": 2}


class ToolRegistry:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        specs: Sequence[ToolSpec] = BUILTIN_SPECS,
    ) -> None:
        self._session_factory = session_factory
        self._specs = tuple(specs)

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return self._specs

    def spec_for_model_name(self, model_name: str) -> ToolSpec | None:
        return _SPECS_BY_MODEL_NAME.get(model_name)

    def spec_for_name(self, name: str) -> ToolSpec | None:
        return _SPECS_BY_NAME.get(name)

    def model_name_for(self, name: str) -> str | None:
        spec = _SPECS_BY_NAME.get(name)
        return spec.model_name if spec is not None else None

    async def sync_builtins(self) -> int:
        """Mirror builtin specs into ``tool_definition`` and grant them.

        Builtin tools are platform code (Q2): they are granted globally, while
        MCP tools stay default-deny in M3.
        """
        async with self._session_factory() as session:
            for spec in self._specs:
                definition = await tools_repo.upsert_definition(
                    session,
                    name=spec.name,
                    kind=spec.kind,
                    display_name=spec.display_name,
                    description=spec.description,
                    input_schema=spec.input_schema(),
                    risk_level=spec.risk_level,
                    requires_approval=spec.requires_approval,
                )
                await tools_repo.upsert_grant(
                    session,
                    tool_definition_id=definition.id,
                    scope="global",
                    scope_id=None,
                    allowed=True,
                    risk_acknowledged=True,
                    granted_by="system",
                )
        return len(self._specs)

    async def list_for_run(
        self,
        *,
        task_id: UUID | None,
        conversation_id: UUID | None,
    ) -> list[ToolSpec]:
        """Tools the model is allowed to see for this run (layer 1: hiding)."""
        offered: list[ToolSpec] = []
        async with self._session_factory() as session:
            for spec in self._specs:
                decision = await self._authorize(
                    session,
                    spec,
                    task_id=task_id,
                    conversation_id=conversation_id,
                )
                if _exposable(decision):
                    offered.append(spec)
            offered.extend(
                await self._mcp_specs(
                    session,
                    task_id=task_id,
                    conversation_id=conversation_id,
                )
            )
        return offered

    async def authorize(
        self,
        model_name: str,
        *,
        task_id: UUID | None,
        conversation_id: UUID | None,
    ) -> AuthorizationDecision:
        spec = _SPECS_BY_MODEL_NAME.get(model_name)
        async with self._session_factory() as session:
            if spec is not None:
                return await self._authorize(
                    session,
                    spec,
                    task_id=task_id,
                    conversation_id=conversation_id,
                )
            for mcp_spec in await self._mcp_specs(
                session,
                task_id=task_id,
                conversation_id=conversation_id,
                authorized_only=False,
            ):
                if mcp_spec.model_name == model_name:
                    definition = await tools_repo.get_definition_by_name(session, mcp_spec.name)
                    if definition is None:
                        break
                    return await self._authorize(
                        session,
                        mcp_spec,
                        task_id=task_id,
                        conversation_id=conversation_id,
                        definition=definition,
                    )
        return AuthorizationDecision(
            allowed=False,
            reason="unknown_tool",
            effective_scope="none",
        )

    def requires_approval(self, model_name: str) -> bool:
        spec = _SPECS_BY_MODEL_NAME.get(model_name)
        return bool(spec and spec.requires_approval)

    def _risk_blocks(self, spec: ToolSpec) -> bool:
        # ``destructive`` always needs a fresh per-call approval (03 §9.1).
        return spec.risk_level == "destructive" or spec.requires_approval

    async def _mcp_specs(
        self,
        session: AsyncSession,
        *,
        task_id: UUID | None,
        conversation_id: UUID | None,
        authorized_only: bool = True,
    ) -> list[ToolSpec]:
        """MCP tools from enabled servers, optionally narrowed to authorized ones."""
        rows = await tools_repo.list_mcp_definitions(session)
        specs: list[ToolSpec] = []
        for definition, server in rows:
            if not definition.enabled or not server.enabled or server.status == "error":
                continue
            spec = _mcp_tool_spec(definition, server)
            if not authorized_only:
                specs.append(spec)
                continue
            decision = await self._authorize(
                session,
                spec,
                task_id=task_id,
                conversation_id=conversation_id,
                definition=definition,
            )
            if _exposable(decision):
                specs.append(spec)
        return specs

    async def _authorize(
        self,
        session: AsyncSession,
        spec: ToolSpec,
        *,
        task_id: UUID | None,
        conversation_id: UUID | None,
        definition: ToolDefinition | None = None,
    ) -> AuthorizationDecision:
        if definition is None:
            definition = await tools_repo.get_definition_by_name(session, spec.name)
        if definition is None or not definition.enabled:
            return AuthorizationDecision(
                allowed=False,
                reason="denied",
                effective_scope="none",
            )

        grants = await tools_repo.grants_for(
            session,
            definition.id,
            conversation_id=conversation_id,
            task_id=task_id,
        )
        winner = select_grant(grants, task_id=task_id, conversation_id=conversation_id)
        if winner is None:
            return AuthorizationDecision(
                allowed=False,
                reason="denied",
                effective_scope="none",
            )

        scope = winner.scope
        if scope not in _SCOPE_PRIORITY:  # pragma: no cover - schema guarantees it
            scope = "global"
        if not winner.allowed:
            return AuthorizationDecision(
                allowed=False,
                reason="denied",
                effective_scope=scope,  # type: ignore[arg-type]
            )
        if self._risk_blocks(spec):
            return AuthorizationDecision(
                allowed=False,
                reason="needs_approval",
                effective_scope=scope,  # type: ignore[arg-type]
            )
        if spec.risk_level == "write" and not winner.risk_acknowledged:
            return AuthorizationDecision(
                allowed=False,
                reason="risk_unacknowledged",
                effective_scope=scope,  # type: ignore[arg-type]
            )
        return AuthorizationDecision(
            allowed=True,
            reason="granted",
            effective_scope=scope,  # type: ignore[arg-type]
        )


def _mcp_tool_spec(definition: ToolDefinition, server: MCPServer) -> ToolSpec:
    """Project a discovered MCP definition into a registry spec."""
    raw_name = definition.name.split(".", 2)[-1]
    return ToolSpec(
        name=definition.name,
        model_name=mcp_model_name(server.slug, raw_name),
        kind="mcp",
        risk_level=definition.risk_level,
        requires_approval=definition.requires_approval,
        display_name=definition.display_name,
        description=definition.description,
        source_id=definition.source_id,
        source_slug=server.slug,
        model_name_raw=raw_name,
    )


def _exposable(decision: AuthorizationDecision) -> bool:
    """A tool is visible to the model when allowed *or* only gated by approval.

    ``needs_approval`` must not hide the tool: it has to reach the toolset so the
    approval gate can pause the call instead of the model seeing an unknown tool.
    """
    return decision.allowed or decision.reason == "needs_approval"


def select_grant(
    grants: Sequence[ToolGrant],
    *,
    task_id: UUID | None,
    conversation_id: UUID | None,
) -> ToolGrant | None:
    """Pick the most specific applicable grant: task > conversation > global."""
    candidates: list[ToolGrant] = []
    for grant in grants:
        if grant.scope == "task" and task_id is not None and grant.scope_id == task_id:
            candidates.append(grant)
        elif (
            grant.scope == "conversation"
            and conversation_id is not None
            and grant.scope_id == conversation_id
        ):
            candidates.append(grant)
        elif grant.scope == "global" and grant.scope_id is None:
            candidates.append(grant)
    if not candidates:
        return None
    return min(candidates, key=lambda grant: _SCOPE_PRIORITY[grant.scope])
