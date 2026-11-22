"""Conversation and message persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from reportify.db.models import Conversation, Message


async def list_conversations(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
) -> Sequence[Conversation]:
    query = select(Conversation)
    if status is not None:
        query = query.where(Conversation.status == status)
    query = query.order_by(
        func.coalesce(Conversation.last_message_at, Conversation.created_at).desc(),
        Conversation.created_at.desc(),
    )
    return (await session.execute(query.limit(limit).offset(offset))).scalars().all()


async def get_conversation(
    session: AsyncSession,
    conversation_id: UUID,
    *,
    for_update: bool = False,
) -> Conversation | None:
    query = select(Conversation).where(Conversation.id == conversation_id)
    if for_update:
        query = query.with_for_update()
    return await session.scalar(query)


async def create_conversation(
    session: AsyncSession,
    *,
    title: str,
    workspace_key: str = "default",
) -> Conversation:
    conversation = Conversation(title=title, workspace_key=workspace_key)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def next_sequence(session: AsyncSession, conversation_id: UUID) -> int:
    current = await session.scalar(
        select(func.coalesce(func.max(Message.sequence), 0)).where(
            Message.conversation_id == conversation_id
        )
    )
    return int(current or 0) + 1


async def append_message(
    session: AsyncSession,
    conversation_id: UUID,
    *,
    role: str,
    message_type: str,
    content: str = "",
    payload: dict[str, Any] | None = None,
    task_id: UUID | None = None,
    run_id: UUID | None = None,
) -> Message:
    """Append a message, allocating the conversation-scoped sequence.

    The conversation row is locked so two writers cannot pick the same sequence;
    the unique constraint is the final backstop.
    """
    for _ in range(2):
        conversation = await get_conversation(session, conversation_id, for_update=True)
        if conversation is None:
            raise LookupError(f"conversation not found: {conversation_id}")
        sequence = await next_sequence(session, conversation_id)
        message = Message(
            conversation_id=conversation_id,
            task_id=task_id,
            run_id=run_id,
            sequence=sequence,
            role=role,
            message_type=message_type,
            content=content,
            payload=payload or {},
        )
        conversation.last_message_at = datetime.now(UTC)
        session.add(message)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            continue
        await session.refresh(message)
        return message
    raise RuntimeError(f"could not allocate message sequence: {conversation_id}")


async def list_messages(
    session: AsyncSession,
    conversation_id: UUID,
    *,
    after_sequence: int = 0,
    limit: int = 100,
) -> Sequence[Message]:
    rows = await session.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.sequence > after_sequence,
        )
        .order_by(Message.sequence)
        .limit(limit)
    )
    return rows.scalars().all()


async def conversation_messages_for_context(
    session: AsyncSession,
    conversation_id: UUID,
    *,
    limit: int = 40,
) -> Sequence[Message]:
    """Most recent user/assistant text, oldest first, for history rebuild."""
    rows = await session.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.message_type.in_(["user_message", "assistant_message"]),
        )
        .order_by(Message.sequence.desc())
        .limit(limit)
    )
    return list(reversed(rows.scalars().all()))
