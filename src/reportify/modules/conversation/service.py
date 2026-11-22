"""Conversation, message and task services.

The service owns product semantics (05): which task a message belongs to, and how
conversation-level state moves. Run execution itself belongs to the runtime.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.core.errors import InvalidArgument, NotFound
from reportify.db.models import AnalysisTask, Conversation, Message, TaskRun
from reportify.db.repositories import conversations as conversations_repo
from reportify.db.repositories import tasks as tasks_repo
from reportify.modules.conversation.schemas import (
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    MessagePage,
    MessageRead,
    RunRead,
    TaskDetail,
    TaskRead,
)


class ConversationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        max_prompt_chars: int = 20_000,
    ) -> None:
        self._session_factory = session_factory
        self._max_prompt_chars = max_prompt_chars

    async def create(self, payload: ConversationCreate) -> Conversation:
        async with self._session_factory() as session:
            return await conversations_repo.create_conversation(
                session,
                title=(payload.title or "新会话").strip() or "新会话",
            )

    async def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> Sequence[Conversation]:
        async with self._session_factory() as session:
            return await conversations_repo.list_conversations(
                session,
                limit=limit,
                offset=offset,
                status=status,
            )

    async def get(self, conversation_id: UUID) -> Conversation:
        async with self._session_factory() as session:
            conversation = await conversations_repo.get_conversation(session, conversation_id)
            if conversation is None:
                raise NotFound(f"conversation not found: {conversation_id}")
            return conversation

    async def update(self, conversation_id: UUID, payload: ConversationUpdate) -> Conversation:
        async with self._session_factory() as session:
            conversation = await conversations_repo.get_conversation(session, conversation_id)
            if conversation is None:
                raise NotFound(f"conversation not found: {conversation_id}")
            if payload.title is not None:
                conversation.title = payload.title.strip() or conversation.title
            if payload.status is not None:
                conversation.status = payload.status
            await session.commit()
            await session.refresh(conversation)
            return conversation

    async def list_messages(
        self,
        conversation_id: UUID,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> MessagePage:
        async with self._session_factory() as session:
            conversation = await conversations_repo.get_conversation(session, conversation_id)
            if conversation is None:
                raise NotFound(f"conversation not found: {conversation_id}")
            rows = await conversations_repo.list_messages(
                session,
                conversation_id,
                after_sequence=after_sequence,
                limit=limit + 1,
            )
            has_more = len(rows) > limit
            page = rows[:limit]
            return MessagePage(
                items=[MessageRead.model_validate(row) for row in page],
                next_after_sequence=page[-1].sequence if has_more and page else None,
                has_more=has_more,
            )

    async def send_message(
        self,
        conversation_id: UUID,
        payload: MessageCreate,
    ) -> tuple[Message, AnalysisTask]:
        """Persist the user message and resolve the task it belongs to."""
        content = payload.content.strip()
        if not content:
            raise InvalidArgument("content must not be empty")
        if len(content) > self._max_prompt_chars:
            raise InvalidArgument(
                f"content exceeds {self._max_prompt_chars} characters"
            )

        async with self._session_factory() as session:
            conversation = await conversations_repo.get_conversation(session, conversation_id)
            if conversation is None:
                raise NotFound(f"conversation not found: {conversation_id}")
            if conversation.status != "active":
                raise InvalidArgument("conversation is archived")

            task = await self._resolve_task(
                session,
                conversation_id=conversation_id,
                requested_task_id=payload.task_id,
                content=content,
                skill_names=payload.skill_names,
                template_name=payload.template_name,
            )

            message = await conversations_repo.append_message(
                session,
                conversation_id,
                role="user",
                message_type="user_message",
                content=content,
                payload={
                    "skill_names": payload.skill_names,
                    "template_name": payload.template_name,
                },
                task_id=task.id,
            )
            return message, task

    async def _resolve_task(
        self,
        session: AsyncSession,
        *,
        conversation_id: UUID,
        requested_task_id: UUID | None,
        content: str,
        skill_names: list[str],
        template_name: str | None,
    ) -> AnalysisTask:
        if requested_task_id is not None:
            task = await tasks_repo.get_task(session, requested_task_id)
            if task is None or task.conversation_id != conversation_id:
                raise NotFound(f"task not found in conversation: {requested_task_id}")
            if skill_names:
                task.skill_names = list(skill_names)
            if template_name is not None:
                task.template_name = template_name
            await session.commit()
            return task

        return await tasks_repo.create_task(
            session,
            conversation_id=conversation_id,
            goal=content,
            skill_names=skill_names,
            template_name=template_name,
        )

    async def get_task(self, task_id: UUID) -> AnalysisTask:
        async with self._session_factory() as session:
            task = await tasks_repo.get_task(session, task_id)
            if task is None:
                raise NotFound(f"task not found: {task_id}")
            return task

    async def task_detail(self, task_id: UUID) -> TaskDetail:
        async with self._session_factory() as session:
            task = await tasks_repo.get_task(session, task_id)
            if task is None:
                raise NotFound(f"task not found: {task_id}")
            runs = (
                await session.execute(
                    select(TaskRun)
                    .where(TaskRun.task_id == task_id)
                    .order_by(TaskRun.created_at.desc())
                )
            ).scalars().all()
            return TaskDetail(
                **TaskRead.model_validate(task).model_dump(),
                runs=[RunRead.model_validate(run) for run in runs],
            )

    async def list_tasks(
        self,
        conversation_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskRead]:
        async with self._session_factory() as session:
            tasks = await tasks_repo.list_tasks(
                session,
                conversation_id,
                limit=limit,
                offset=offset,
            )
            return [TaskRead.model_validate(task) for task in tasks]
