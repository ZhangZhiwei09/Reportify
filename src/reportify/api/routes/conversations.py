"""Conversation and message routes (05 §10, 07 §5.1)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from reportify.api.deps import (
    get_conversation_service,
    get_runtime,
    require_auth,
)
from reportify.core.errors import ConversationBusy
from reportify.modules.conversation.schemas import (
    ConversationCreate,
    ConversationRead,
    ConversationUpdate,
    MessageCreate,
    MessagePage,
    SendMessageResult,
    TaskRead,
)
from reportify.modules.conversation.service import ConversationService
from reportify.modules.runtime.runtime import AgentRuntime
from reportify.modules.runtime.schemas import RunRequest

router = APIRouter(
    prefix="/api/v1/conversations",
    tags=["conversations"],
    dependencies=[Depends(require_auth)],
)


@router.get("", response_model=list[ConversationRead])
async def list_conversations(
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[ConversationRead]:
    rows = await service.list(limit=limit, offset=offset, status=status_filter)
    return [ConversationRead.model_validate(row) for row in rows]


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationRead:
    conversation = await service.create(payload)
    return ConversationRead.model_validate(conversation)


@router.get("/{conversation_id}", response_model=ConversationRead)
async def get_conversation(
    conversation_id: UUID,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationRead:
    conversation = await service.get(conversation_id)
    return ConversationRead.model_validate(conversation)


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationRead:
    conversation = await service.update(conversation_id, payload)
    return ConversationRead.model_validate(conversation)


@router.get("/{conversation_id}/messages", response_model=MessagePage)
async def list_messages(
    conversation_id: UUID,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> MessagePage:
    return await service.list_messages(
        conversation_id,
        after_sequence=after_sequence,
        limit=limit,
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=SendMessageResult,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    conversation_id: UUID,
    payload: MessageCreate,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> SendMessageResult:
    await service.get(conversation_id)  # 404 before any write
    if await runtime.has_active_run(conversation_id):
        raise ConversationBusy()

    message, task = await service.send_message(conversation_id, payload)
    run_id = await runtime.start(
        RunRequest(
            conversation_id=conversation_id,
            task_id=task.id,
            user_message_id=message.id,
            skill_names=tuple(payload.skill_names),
            template_name=payload.template_name,
        )
    )
    return SendMessageResult(message_id=message.id, task_id=task.id, run_id=run_id)


@router.get("/{conversation_id}/tasks", response_model=list[TaskRead])
async def list_tasks(
    conversation_id: UUID,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TaskRead]:
    return await service.list_tasks(conversation_id, limit=limit, offset=offset)
