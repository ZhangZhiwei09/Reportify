"""Analysis task routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.api.deps import (
    get_conversation_service,
    get_runtime,
    get_session_factory,
    require_auth,
)
from reportify.core.errors import InvalidArgument
from reportify.db.models import Message
from reportify.modules.conversation.schemas import RunRead, TaskDetail
from reportify.modules.conversation.service import ConversationService
from reportify.modules.runtime.runtime import AgentRuntime
from reportify.modules.runtime.schemas import RunRequest

router = APIRouter(
    prefix="/api/v1/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_auth)],
)


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(
    task_id: UUID,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> TaskDetail:
    return await service.task_detail(task_id)


@router.post("/{task_id}/runs", response_model=RunRead, status_code=status.HTTP_201_CREATED)
async def start_run(
    task_id: UUID,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
    session_factory: Annotated[
        async_sessionmaker[AsyncSession], Depends(get_session_factory)
    ],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> RunRead:
    task = await service.get_task(task_id)
    async with session_factory() as session:
        message = await _latest_user_message(session, task_id)
    if message is None:
        raise InvalidArgument("task has no user message to re-run")

    key = (idempotency_key or "").strip() or None
    if key is not None and len(key) > 160:
        raise InvalidArgument("Idempotency-Key must be at most 160 characters")

    run_id = await runtime.start(
        RunRequest(
            conversation_id=task.conversation_id,
            task_id=task.id,
            user_message_id=message.id,
            skill_names=tuple(task.skill_names or ()),
            template_name=task.template_name,
            idempotency_key=key,
        )
    )
    run = await runtime.get_run(run_id)
    return RunRead.model_validate(run)


async def _latest_user_message(session: AsyncSession, task_id: UUID) -> Message | None:
    return await session.scalar(
        select(Message)
        .where(Message.task_id == task_id, Message.message_type == "user_message")
        .order_by(Message.sequence.desc())
        .limit(1)
    )
