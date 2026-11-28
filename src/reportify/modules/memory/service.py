"""Long-term memory: store user-confirmed notes and recall the relevant ones.

Scope model is intentionally small (02 §8 step 6): a note is either global or
attached to one conversation. Retrieval is lexical — see ``retrieval.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.core.errors import InvalidArgument, NotFound
from reportify.db.models import Conversation, Memory
from reportify.modules.memory.retrieval import rank
from reportify.modules.memory.schemas import (
    MemoryCreate,
    MemoryItem,
    MemoryRead,
)

CANDIDATE_LIMIT = 500

class MemoryService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        max_items: int = 5,
    ) -> None:
        self._session_factory = session_factory
        self._max_items = max(1, max_items)

    async def add(self, payload: MemoryCreate) -> MemoryRead:
        async with self._session_factory() as session:
            if payload.scope == "conversation":
                conversation = await session.get(Conversation, payload.conversation_id)
                if conversation is None:
                    raise NotFound(
                        f"conversation not found: {payload.conversation_id}"
                    )
            memory = Memory(
                scope=payload.scope,
                scope_id=payload.conversation_id,
                kind=payload.kind,
                content=payload.content.strip(),
                tags=list(payload.tags),
                created_by="user",
            )
            session.add(memory)
            await session.commit()
            await session.refresh(memory)
            return MemoryRead.model_validate(memory)

    async def list(
        self,
        *,
        scope: str | None = None,
        conversation_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRead]:
        async with self._session_factory() as session:
            query = select(Memory).order_by(Memory.created_at.desc())
            if scope is not None:
                if scope not in {"global", "conversation"}:
                    raise InvalidArgument(f"unknown memory scope: {scope}")
                query = query.where(Memory.scope == scope)
                if scope == "conversation" and conversation_id is not None:
                    query = query.where(Memory.scope_id == conversation_id)
            rows = (
                await session.execute(query.limit(limit).offset(offset))
            ).scalars().all()
            return [MemoryRead.model_validate(row) for row in rows]

    async def delete(self, memory_id: UUID) -> None:
        async with self._session_factory() as session:
            memory = await session.get(Memory, memory_id)
            if memory is None:
                raise NotFound(f"memory not found: {memory_id}")
            await session.delete(memory)
            await session.commit()

    async def search(
        self,
        query: str,
        *,
        conversation_id: UUID | None = None,
        limit: int | None = None,
    ) -> list[MemoryItem]:
        """Rank visible notes for a goal; marks the recalled ones as used."""
        async with self._session_factory() as session:
            conditions = [Memory.scope == "global"]
            if conversation_id is not None:
                conditions.append(
                    (Memory.scope == "conversation")
                    & (Memory.scope_id == conversation_id)
                )
            rows = (
                await session.execute(
                    select(Memory)
                    .where(or_(*conditions))
                    .order_by(Memory.created_at.desc())
                    .limit(CANDIDATE_LIMIT)
                )
            ).scalars().all()
            items = rank(query, list(rows), limit=limit or self._max_items)
            if items:
                used_ids = {item.id for item in items}
                now = datetime.now(UTC)
                for row in rows:
                    if row.id in used_ids:
                        row.last_used_at = now
                await session.commit()
            return items
