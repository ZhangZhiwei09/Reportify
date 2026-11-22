"""Tool registry, grant and audit persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from reportify.db.models import ToolCallAudit, ToolDefinition, ToolGrant


async def get_definition_by_name(session: AsyncSession, name: str) -> ToolDefinition | None:
    return await session.scalar(select(ToolDefinition).where(ToolDefinition.name == name))


async def list_definitions(
    session: AsyncSession,
    *,
    enabled_only: bool = True,
    kinds: Sequence[str] | None = None,
) -> Sequence[ToolDefinition]:
    query = select(ToolDefinition)
    if enabled_only:
        query = query.where(ToolDefinition.enabled.is_(True))
    if kinds:
        query = query.where(ToolDefinition.kind.in_(list(kinds)))
    return (await session.execute(query.order_by(ToolDefinition.name))).scalars().all()


async def upsert_definition(
    session: AsyncSession,
    *,
    name: str,
    kind: str,
    display_name: str,
    description: str,
    input_schema: dict[str, Any],
    risk_level: str,
    requires_approval: bool,
    output_schema: dict[str, Any] | None = None,
) -> ToolDefinition:
    existing = await get_definition_by_name(session, name)
    if existing is None:
        definition = ToolDefinition(
            name=name,
            kind=kind,
            display_name=display_name,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            risk_level=risk_level,
            requires_approval=requires_approval,
            enabled=True,
            discovered_at=datetime.now(UTC),
        )
        session.add(definition)
    else:
        definition = existing
        definition.kind = kind
        definition.display_name = display_name
        definition.description = description
        definition.input_schema = input_schema
        definition.output_schema = output_schema
        definition.risk_level = risk_level
        definition.requires_approval = requires_approval
        definition.enabled = True
    await session.commit()
    await session.refresh(definition)
    return definition


async def grants_for(
    session: AsyncSession,
    tool_definition_id: UUID,
    *,
    conversation_id: UUID | None = None,
    task_id: UUID | None = None,
) -> list[ToolGrant]:
    """Grants applicable to one tool in this run's context.

    Resolution order (task > conversation > global) is applied by the caller; the
    query only narrows the candidate set.
    """
    scope_ids = [value for value in (conversation_id, task_id) if value is not None]
    query = select(ToolGrant).where(ToolGrant.tool_definition_id == tool_definition_id)
    if scope_ids:
        query = query.where(
            (ToolGrant.scope == "global") | (ToolGrant.scope_id.in_(scope_ids))
        )
    else:
        query = query.where(ToolGrant.scope == "global")
    return list((await session.execute(query)).scalars().all())


async def upsert_grant(
    session: AsyncSession,
    *,
    tool_definition_id: UUID,
    scope: str,
    scope_id: UUID | None,
    allowed: bool,
    risk_acknowledged: bool = False,
    granted_by: str = "local",
) -> ToolGrant:
    existing = await session.scalar(
        select(ToolGrant).where(
            ToolGrant.tool_definition_id == tool_definition_id,
            ToolGrant.scope == scope,
            ToolGrant.scope_id.is_(None) if scope_id is None else ToolGrant.scope_id == scope_id,
        )
    )
    if existing is None:
        grant = ToolGrant(
            tool_definition_id=tool_definition_id,
            scope=scope,
            scope_id=scope_id,
            allowed=allowed,
            risk_acknowledged=risk_acknowledged,
            granted_by=granted_by,
        )
        session.add(grant)
    else:
        grant = existing
        grant.allowed = allowed
        grant.risk_acknowledged = risk_acknowledged
        grant.granted_by = granted_by
    await session.commit()
    await session.refresh(grant)
    return grant


async def upsert_mcp_definition(
    session: AsyncSession,
    *,
    name: str,
    source_id: UUID,
    display_name: str,
    description: str,
    input_schema: dict[str, Any],
) -> tuple[ToolDefinition, bool]:
    """Create an MCP tool definition, or refresh the discovery-owned fields.

    ``risk_level``, ``requires_approval`` and ``enabled`` are user/platform state:
    a re-discovery must never silently reset them (03 §7.3).
    """
    existing = await get_definition_by_name(session, name)
    if existing is None:
        definition = ToolDefinition(
            name=name,
            kind="mcp",
            source_id=source_id,
            display_name=display_name,
            description=description,
            input_schema=input_schema,
            risk_level="write",  # conservative default, never inferred
            requires_approval=False,
            enabled=True,
            discovered_at=datetime.now(UTC),
        )
        session.add(definition)
        await session.commit()
        await session.refresh(definition)
        return definition, True

    definition = existing
    definition.kind = "mcp"
    definition.source_id = source_id
    definition.display_name = display_name
    definition.description = description
    definition.input_schema = input_schema
    definition.discovered_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(definition)
    return definition, False


async def set_definition_enabled(
    session: AsyncSession,
    *,
    source_id: UUID,
    name: str,
    enabled: bool,
) -> None:
    definition = await get_definition_by_name(session, name)
    if definition is not None and definition.source_id == source_id:
        definition.enabled = enabled
        await session.commit()


async def list_mcp_definitions(
    session: AsyncSession,
    *,
    source_id: UUID | None = None,
) -> list[tuple[ToolDefinition, Any]]:
    """Join MCP tool definitions with their server."""
    from reportify.db.models import MCPServer

    statement = (
        select(ToolDefinition, MCPServer)
        .join(MCPServer, ToolDefinition.source_id == MCPServer.id)
        .where(ToolDefinition.kind == "mcp")
    )
    if source_id is not None:
        statement = statement.where(ToolDefinition.source_id == source_id)
    rows = await session.execute(statement.order_by(ToolDefinition.name))
    return [(definition, server) for definition, server in rows.all()]


async def reset_grant_acknowledgement(
    session: AsyncSession,
    *,
    tool_definition_id: UUID,
) -> None:
    """Schema changed: write tools must be re-confirmed by the user."""
    await session.execute(
        update(ToolGrant)
        .where(ToolGrant.tool_definition_id == tool_definition_id)
        .values(risk_acknowledged=False)
    )
    await session.commit()


async def write_audit(
    session: AsyncSession,
    *,
    run_id: UUID,
    tool_name: str,
    source: str,
    status: str,
    tool_definition_id: UUID | None = None,
    arguments_redacted: dict[str, Any] | None = None,
    result_summary: dict[str, Any] | None = None,
    error_code: str | None = None,
    duration_ms: int | None = None,
) -> ToolCallAudit:
    audit = ToolCallAudit(
        run_id=run_id,
        tool_definition_id=tool_definition_id,
        tool_name=tool_name,
        source=source,
        arguments_redacted=arguments_redacted or {},
        result_summary=result_summary or {},
        status=status,
        error_code=error_code,
        duration_ms=duration_ms,
    )
    session.add(audit)
    await session.commit()
    return audit


async def list_audits(
    session: AsyncSession,
    *,
    run_id: UUID | None = None,
    tool_name: str | None = None,
    source: str | None = None,
    name_prefix: str | None = None,
    limit: int = 100,
) -> Sequence[ToolCallAudit]:
    query = select(ToolCallAudit)
    if run_id is not None:
        query = query.where(ToolCallAudit.run_id == run_id)
    if tool_name is not None:
        query = query.where(ToolCallAudit.tool_name == tool_name)
    if source is not None:
        query = query.where(ToolCallAudit.source == source)
    if name_prefix is not None:
        query = query.where(ToolCallAudit.tool_name.startswith(name_prefix))
    rows = await session.execute(
        query.order_by(ToolCallAudit.created_at.desc()).limit(limit)
    )
    return rows.scalars().all()
