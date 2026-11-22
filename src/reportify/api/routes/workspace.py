"""Workspace file and audit routes (07 §5.4)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from reportify.api.deps import get_workspace_service, require_auth
from reportify.modules.workspace.service import WorkspaceService

router = APIRouter(
    prefix="/api/v1/workspace",
    tags=["workspace"],
    dependencies=[Depends(require_auth)],
)


@router.get("/files")
async def list_files(
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> dict[str, Any]:
    files = service.list_files()
    return {"files": files, "count": len(files)}


@router.post("/reload")
async def reload_workspace(
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> dict[str, Any]:
    return await service.reload()


@router.get("/audits")
async def list_audits(
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    action: str | None = None,
) -> list[dict[str, Any]]:
    return await service.audits(limit=limit, action=action)


@router.get("/files/{path:path}")
async def read_file(
    path: str,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> dict[str, Any]:
    return service.read_file(path)
