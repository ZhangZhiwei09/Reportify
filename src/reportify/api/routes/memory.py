"""Long-term memory routes (07 §5, M10)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from reportify.api.deps import get_memory_service, require_auth
from reportify.modules.memory.schemas import (
    MemoryCreate,
    MemoryItem,
    MemoryRead,
)
from reportify.modules.memory.service import MemoryService

router = APIRouter(
    prefix="/api/v1/memory",
    tags=["memory"],
    dependencies=[Depends(require_auth)],
)


@router.get("", response_model=list[MemoryRead])
async def list_memory(
    service: Annotated[MemoryService, Depends(get_memory_service)],
    scope: Annotated[str | None, Query()] = None,
    conversation_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MemoryRead]:
    return await service.list(
        scope=scope,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def add_memory(
    payload: MemoryCreate,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryRead:
    return await service.add(payload)


@router.get("/search", response_model=list[MemoryItem])
async def search_memory(
    service: Annotated[MemoryService, Depends(get_memory_service)],
    q: Annotated[str, Query(min_length=1, max_length=500)],
    conversation_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[MemoryItem]:
    return await service.search(q, conversation_id=conversation_id, limit=limit)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: UUID,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> None:
    await service.delete(memory_id)
