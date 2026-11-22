"""MCP Server management routes (07 §5.3)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.api.deps import get_mcp_hub, get_session_factory, require_auth
from reportify.db.repositories import tools as tools_repo
from reportify.modules.mcp.hub import MCPHub
from reportify.modules.mcp.schemas import (
    DiscoveryResult,
    GrantRequest,
    MCPServerCreate,
    MCPServerRead,
    MCPServerUpdate,
    MCPTestResult,
    MCPToolView,
)

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"], dependencies=[Depends(require_auth)])


@router.get("/servers", response_model=list[MCPServerRead])
async def list_servers(
    hub: Annotated[MCPHub, Depends(get_mcp_hub)],
) -> list[MCPServerRead]:
    return await hub.list()


@router.post("/servers", response_model=MCPServerRead, status_code=status.HTTP_201_CREATED)
async def create_server(
    payload: MCPServerCreate,
    hub: Annotated[MCPHub, Depends(get_mcp_hub)],
) -> MCPServerRead:
    return await hub.create(payload)


@router.get("/servers/{server_id}", response_model=MCPServerRead)
async def get_server(
    server_id: UUID,
    hub: Annotated[MCPHub, Depends(get_mcp_hub)],
) -> MCPServerRead:
    return await hub.get(server_id)


@router.patch("/servers/{server_id}", response_model=MCPServerRead)
async def update_server(
    server_id: UUID,
    payload: MCPServerUpdate,
    hub: Annotated[MCPHub, Depends(get_mcp_hub)],
) -> MCPServerRead:
    return await hub.update(server_id, payload)


@router.delete("/servers/{server_id}", response_model=MCPServerRead)
async def delete_server(
    server_id: UUID,
    hub: Annotated[MCPHub, Depends(get_mcp_hub)],
) -> MCPServerRead:
    """Soft delete: disable the server and hide its tools."""
    return await hub.disable(server_id)


@router.post("/servers/{server_id}/test", response_model=MCPTestResult)
async def test_server(
    server_id: UUID,
    hub: Annotated[MCPHub, Depends(get_mcp_hub)],
) -> MCPTestResult:
    return await hub.test(server_id)


@router.post("/servers/{server_id}/discover", response_model=DiscoveryResult)
async def discover_tools(
    server_id: UUID,
    hub: Annotated[MCPHub, Depends(get_mcp_hub)],
) -> DiscoveryResult:
    return await hub.discover(server_id)


@router.get("/servers/{server_id}/tools", response_model=list[MCPToolView])
async def list_tools(
    server_id: UUID,
    hub: Annotated[MCPHub, Depends(get_mcp_hub)],
) -> list[MCPToolView]:
    return await hub.list_tools(server_id)


@router.put("/tools/{tool_id}/grant", response_model=MCPToolView)
async def set_grant(
    tool_id: UUID,
    payload: GrantRequest,
    hub: Annotated[MCPHub, Depends(get_mcp_hub)],
) -> MCPToolView:
    return await hub.set_grant(tool_id, payload)


@router.delete("/tools/{tool_id}/grant", response_model=MCPToolView)
async def revoke_grant(
    tool_id: UUID,
    hub: Annotated[MCPHub, Depends(get_mcp_hub)],
) -> MCPToolView:
    return await hub.revoke_grant(tool_id)


@router.get("/audits")
async def list_audits(
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    tool_name: str | None = None,
) -> list[dict]:
    async with session_factory() as session:
        rows = await tools_repo.list_audits(
            session,
            source="mcp",
            tool_name=tool_name,
            limit=limit,
        )
    return [
        {
            "id": str(row.id),
            "run_id": str(row.run_id),
            "tool_name": row.tool_name,
            "status": row.status,
            "error_code": row.error_code,
            "duration_ms": row.duration_ms,
            "arguments_redacted": row.arguments_redacted,
            "result_summary": row.result_summary,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
