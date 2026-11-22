"""MCP server and tool cache persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from reportify.db.models import MCPServer, MCPToolCache


async def list_servers(
    session: AsyncSession,
    *,
    include_disabled: bool = True,
) -> Sequence[MCPServer]:
    query = select(MCPServer).order_by(MCPServer.name)
    if not include_disabled:
        query = query.where(MCPServer.enabled.is_(True))
    return (await session.execute(query)).scalars().all()


async def get_server(session: AsyncSession, server_id: UUID) -> MCPServer | None:
    return await session.get(MCPServer, server_id)


async def get_by_slug(session: AsyncSession, slug: str) -> MCPServer | None:
    return await session.scalar(select(MCPServer).where(MCPServer.slug == slug))


async def get_by_name(session: AsyncSession, name: str) -> MCPServer | None:
    return await session.scalar(select(MCPServer).where(MCPServer.name == name))


async def create_server(session: AsyncSession, **fields: Any) -> MCPServer:
    server = MCPServer(**fields)
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return server


async def update_server(
    session: AsyncSession,
    server: MCPServer,
    **fields: Any,
) -> MCPServer:
    for key, value in fields.items():
        setattr(server, key, value)
    await session.commit()
    await session.refresh(server)
    return server


async def set_status(
    session: AsyncSession,
    server_id: UUID,
    *,
    status: str,
    last_error: str | None = None,
    server_info: dict[str, Any] | None = None,
    protocol_version: str | None = None,
    tested: bool = True,
) -> None:
    server = await session.get(MCPServer, server_id)
    if server is None:
        return
    server.status = status
    server.last_error = last_error
    if server_info is not None:
        server.server_info = server_info
    if protocol_version is not None:
        server.protocol_version = protocol_version
    if tested:
        server.last_tested_at = datetime.now(UTC)
    await session.commit()


async def list_cache(session: AsyncSession, server_id: UUID) -> Sequence[MCPToolCache]:
    rows = await session.execute(
        select(MCPToolCache)
        .where(MCPToolCache.mcp_server_id == server_id)
        .order_by(MCPToolCache.tool_name)
    )
    return rows.scalars().all()


async def upsert_cache(
    session: AsyncSession,
    *,
    server_id: UUID,
    tool_name: str,
    description: str,
    input_schema: dict[str, Any],
    annotations: dict[str, Any],
    schema_hash: str,
) -> tuple[MCPToolCache, bool]:
    """Insert or update a cache row. Returns (row, schema_changed)."""
    existing = await session.scalar(
        select(MCPToolCache).where(
            MCPToolCache.mcp_server_id == server_id,
            MCPToolCache.tool_name == tool_name,
        )
    )
    if existing is None:
        row = MCPToolCache(
            mcp_server_id=server_id,
            tool_name=tool_name,
            description=description,
            input_schema=input_schema,
            annotations=annotations,
            schema_hash=schema_hash,
            discovered_at=datetime.now(UTC),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row, False

    changed = existing.schema_hash != schema_hash
    existing.description = description
    existing.input_schema = input_schema
    existing.annotations = annotations
    existing.schema_hash = schema_hash
    existing.discovered_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(existing)
    return existing, changed


async def delete_cache_not_in(
    session: AsyncSession,
    server_id: UUID,
    keep: Sequence[str],
) -> list[str]:
    """Remove cache rows for tools the server no longer exposes."""
    rows = await list_cache(session, server_id)
    removable = [row.tool_name for row in rows if row.tool_name not in set(keep)]
    if removable:
        await session.execute(
            delete(MCPToolCache).where(
                MCPToolCache.mcp_server_id == server_id,
                MCPToolCache.tool_name.in_(removable),
            )
        )
        await session.commit()
    return removable
