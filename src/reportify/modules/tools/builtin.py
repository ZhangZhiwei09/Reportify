"""Builtin tools exposed to the model (03 §5).

Every tool returns a :class:`ToolResult` envelope. Failures are values, not
exceptions, so the model can adapt instead of the run dying. Raw SQL is never
accepted: queries go through ``QuerySpec``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic_ai import RunContext

from reportify.core.errors import ApiError
from reportify.db.models import DatasetSnapshot
from reportify.modules.connectors.errors import DataLayerError
from reportify.modules.connectors.schemas import Lineage, QuerySpec
from reportify.modules.reports.schemas import ReportSchema
from reportify.modules.tools.schemas import ToolResult
from reportify.modules.workspace.loader import WorkspaceValidationError

MAX_TABLES_IN_RESULT = 50
MAX_COLUMNS_IN_RESULT = 200
DEFAULT_PREVIEW_ROWS = 20
MAX_PREVIEW_ROWS = 50


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _lineage_dict(lineage: Lineage | None) -> dict[str, Any] | None:
    if lineage is None:
        return None
    return json.loads(lineage.model_dump_json())


def _failure_from_exception(exc: Exception) -> ToolResult:
    if isinstance(exc, ApiError):
        code = "not_found" if exc.status_code == 404 else "invalid_argument"
        return ToolResult.failure(code, exc.detail)  # type: ignore[arg-type]
    if isinstance(exc, DataLayerError):
        return ToolResult.failure("upstream_error", exc.detail)
    if isinstance(exc, WorkspaceValidationError):
        return ToolResult.failure("not_found", str(exc))
    return ToolResult.failure("internal_error", f"{type(exc).__name__}")


async def _attach_snapshot_to_run(deps: Any, snapshot_id: UUID) -> None:
    """Attribute a dataset snapshot to the current run for lineage (08 §6.5).

    Connectors create snapshots without run context, and this keeps the linkage
    inside the tool layer instead of widening the connector contract.
    """
    try:
        async with deps.session_factory() as session:
            snapshot = await session.get(DatasetSnapshot, snapshot_id)
            if snapshot is not None and snapshot.run_id is None:
                snapshot.run_id = deps.run_id
                await session.commit()
    except Exception:  # noqa: BLE001 - lineage bookkeeping must not fail the tool
        pass


async def inspect_dataset(
    ctx: RunContext[Any],
    data_source_id: UUID,
    schema: str | None = None,
    table: str | None = None,
) -> ToolResult:
    """列出数据源的表与字段（只读）。可传 schema 或 table 缩小范围。

    Returns:
        ToolResult: 表清单与字段清单，含类型与可空性。
    """
    deps = ctx.deps
    await deps.ensure_tool_allowed("inspect_dataset")
    try:
        connector = await deps.connectors.get(data_source_id)
        tables = await connector.inspect_schema()
    except Exception as exc:  # noqa: BLE001 - mapped to a typed envelope
        return _failure_from_exception(exc)

    if schema:
        tables = [item for item in tables if item.schema_name == schema]
    if table:
        tables = [
            item
            for item in tables
            if item.table_name == table or f"{item.schema_name}.{item.table_name}" == table
        ]
    if not tables:
        return ToolResult(
            ok=True,
            summary="没有匹配的表。",
            data={"tables": []},
            warnings=["no tables matched the filter"],
        )

    payload_tables = []
    for item in tables[:MAX_TABLES_IN_RESULT]:
        payload_tables.append(
            {
                "schema": item.schema_name,
                "table": item.table_name,
                "type": item.table_type,
                "row_estimate": item.row_estimate,
                "columns": [
                    {
                        "name": column.name,
                        "native_type": column.native_type,
                        "normalized_type": column.normalized_type,
                        "nullable": column.nullable,
                    }
                    for column in item.columns[:MAX_COLUMNS_IN_RESULT]
                ],
            }
        )
    return ToolResult(
        ok=True,
        summary=f"发现 {len(tables)} 张表（展示 {len(payload_tables)} 张）。",
        data={"tables": payload_tables, "total_tables": len(tables)},
        warnings=(
            [f"truncated to {MAX_TABLES_IN_RESULT} tables"]
            if len(tables) > MAX_TABLES_IN_RESULT
            else []
        ),
        truncated=len(tables) > MAX_TABLES_IN_RESULT,
    )


async def query_dataset(
    ctx: RunContext[Any],
    data_source_id: UUID,
    spec: QuerySpec,
    preview_rows: int = DEFAULT_PREVIEW_ROWS,
) -> ToolResult:
    """用结构化 QuerySpec 做只读查询，返回预览、lineage 与 snapshot_id。

    Args:
        data_source_id: 数据源 ID。
        spec: 结构化查询条件；不支持原始 SQL。
        preview_rows: 返回给模型的行数上限（最多 50）。
    """
    deps = ctx.deps
    await deps.ensure_tool_allowed("query_dataset")
    limit = max(1, min(preview_rows, MAX_PREVIEW_ROWS))
    try:
        connector = await deps.connectors.get(data_source_id)
        result = await connector.execute(spec, purpose="analysis")
    except Exception as exc:  # noqa: BLE001
        return _failure_from_exception(exc)

    columns = [column.name for column in result.columns]
    preview = [
        {column: row[index] for index, column in enumerate(columns)}
        for row in result.rows[:limit]
    ]
    await _attach_snapshot_to_run(deps, result.snapshot_id)
    payload = {
        "columns": columns,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "preview": json.loads(json.dumps(preview, default=_json_default)),
        "snapshot_id": str(result.snapshot_id),
    }
    return ToolResult(
        ok=True,
        summary=(
            f"查询返回 {result.row_count} 行、{len(columns)} 列；"
            f"预览 {len(preview)} 行，snapshot {result.snapshot_id}。"
        ),
        data=payload,
        lineage=result.lineage,
        warnings=["preview only; full result stays server-side"]
        if result.row_count > len(preview)
        else [],
    )


async def fetch_dataset(
    ctx: RunContext[Any],
    snapshot_id: UUID,
    offset: int = 0,
    limit: int = 100,
) -> ToolResult:
    """按 snapshot_id 分页读取上次查询的结果。

    Args:
        snapshot_id: query_dataset 返回的快照 ID。
        offset: 起始偏移。
        limit: 本次读取行数（最多 1000）。
    """
    deps = ctx.deps
    await deps.ensure_tool_allowed("fetch_dataset")
    if offset < 0:
        return ToolResult.failure("invalid_argument", "offset must be >= 0")
    page_size = max(1, min(limit, 1000))
    try:
        async with deps.session_factory() as session:
            snapshot = await session.get(DatasetSnapshot, snapshot_id)
        if snapshot is None:
            return ToolResult.failure("not_found", f"snapshot not found: {snapshot_id}")
        connector = await deps.connectors.get(snapshot.data_source_id)
        page = await connector.fetch_page(snapshot_id, offset, page_size)
    except Exception as exc:  # noqa: BLE001
        return _failure_from_exception(exc)

    return ToolResult(
        ok=True,
        summary=(
            f"读取 {len(page.rows)} 行（offset={page.offset}, limit={page.limit}，"
            f"has_more={page.has_more}）。"
        ),
        data={
            "rows": json.loads(json.dumps(page.rows, default=_json_default)),
            "offset": page.offset,
            "limit": page.limit,
            "has_more": page.has_more,
            "snapshot_id": str(snapshot_id),
        },
    )


async def profile_dataset(
    ctx: RunContext[Any],
    data_source_id: UUID,
    table: str,
    columns: list[str] | None = None,
    sample_size: int = 10_000,
) -> ToolResult:
    """对表采样并计算字段统计（空值率、唯一值、min/max/mean/std、Top 值）。

    Args:
        data_source_id: 数据源 ID。
        table: 表名，可带 schema 前缀。
        columns: 仅统计这些字段；默认全部。
        sample_size: 采样行数上限（最多 100000）。
    """
    deps = ctx.deps
    await deps.ensure_tool_allowed("profile_dataset")
    try:
        profile = await deps.profiling.profile(
            data_source_id,
            table,
            columns=columns,
            sample_size=sample_size,
        )
    except Exception as exc:  # noqa: BLE001
        return _failure_from_exception(exc)

    payload = json.loads(profile.model_dump_json())
    if profile.lineage.snapshot_id is not None:
        await _attach_snapshot_to_run(deps, profile.lineage.snapshot_id)
    return ToolResult(
        ok=True,
        summary=(
            f"表 {profile.table} 采样 {profile.sampled_rows} 行，"
            f"统计 {len(profile.columns)} 个字段。"
        ),
        data=payload,
        lineage=profile.lineage,
        warnings=profile.warnings,
    )


async def load_skill(ctx: RunContext[Any], name: str) -> ToolResult:
    """按名称加载工作区 Skill 的完整说明。

    Args:
        name: Skill 名称（目录名）。
    """
    deps = ctx.deps
    await deps.ensure_tool_allowed("load_skill")
    meta = next((item for item in deps.workspace.skills if item.name == name), None)
    if meta is None:
        available = ", ".join(item.name for item in deps.workspace.skills) or "(none)"
        return ToolResult.failure(
            "not_found",
            f"skill not found: {name}; available: {available}",
        )
    try:
        content = deps.workspace_loader.read_skill(name, deps.workspace.skills)
    except WorkspaceValidationError as exc:
        return ToolResult.failure("not_found", str(exc))

    return ToolResult(
        ok=True,
        summary=f"已加载 Skill {meta.display_name}（{meta.name}）。",
        data={
            "name": meta.name,
            "display_name": meta.display_name,
            "description": meta.description,
            "version": meta.version,
            "content": content,
        },
    )


async def generate_report(
    ctx: RunContext[Any],
    report: ReportSchema,
) -> ToolResult:
    """提交 ReportSchema 生成报告；每个 run 只能调用一次。

    Args:
        report: 经校验的报告结构，指标必须引用已有 dataset_snapshot。
    """
    deps = ctx.deps
    await deps.ensure_tool_allowed("generate_report")
    if deps.report_state.generated:
        return ToolResult.failure(
            "invalid_argument",
            "report_already_generated: this run already produced a report",
        )
    try:
        ref = await deps.reports.generate(
            run_id=deps.run_id,
            task_id=deps.task_id,
            schema=report,
        )
    except Exception as exc:  # noqa: BLE001
        return _failure_from_exception(exc)

    deps.report_state.generated = True
    deps.report_state.report_id = ref.id
    await deps.events.publish(
        deps.run_id,
        "report_generated",
        {
            "report_ref_id": str(ref.id),
            "title": ref.title,
            "renderer": ref.renderer,
            "content_hash": ref.content_hash,
            "status": ref.status,
            "generated_at": datetime.now(UTC).isoformat(),
        },
    )
    return ToolResult(
        ok=True,
        summary=f"报告已生成：{ref.title}（report_ref {ref.id}，占位渲染）。",
        data={
            "report_ref_id": str(ref.id),
            "title": ref.title,
            "renderer": ref.renderer,
            "storage_path": ref.storage_path,
            "note": "placeholder renderer; not a final artifact",
        },
        lineage=None,
    )


BUILTIN_FUNCTIONS: dict[str, Any] = {
    "inspect_dataset": inspect_dataset,
    "query_dataset": query_dataset,
    "fetch_dataset": fetch_dataset,
    "profile_dataset": profile_dataset,
    "load_skill": load_skill,
    "generate_report": generate_report,
}
