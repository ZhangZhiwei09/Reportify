"""Run event persistence and in-process fan-out.

Every event is written to ``run_event`` *before* it is pushed to subscribers, so
the SSE endpoint can always rebuild the stream from PostgreSQL (02 §11).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.db.models import RunEvent

logger = logging.getLogger(__name__)

EventType = Literal[
    "run_started",
    "plan",
    "model_request",
    "tool_call",
    "tool_result",
    "usage",
    "approval_required",
    "report_generated",
    "run_completed",
    "error",
]

TERMINAL_EVENTS: frozenset[str] = frozenset({"run_completed", "error"})

_MAX_SEQUENCE_ATTEMPTS = 3


@dataclass(frozen=True)
class RunEventView:
    """Detached event row; safe to hand to SSE writers."""

    run_id: UUID
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }


class EventBroker:
    """Per-run fan-out to in-process subscribers.

    Redis fan-out would be the multi-worker upgrade; the interface stays the
    same, which is why SSE code never touches PostgreSQL directly.
    """

    def __init__(self) -> None:
        self._subscribers: dict[UUID, set[asyncio.Queue[RunEventView | None]]] = {}

    @contextlib.asynccontextmanager
    async def subscribe(self, run_id: UUID) -> AsyncIterator[asyncio.Queue[RunEventView | None]]:
        queue: asyncio.Queue[RunEventView | None] = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(queue)
        try:
            yield queue
        finally:
            subscribers = self._subscribers.get(run_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(run_id, None)

    def publish(self, event: RunEventView) -> None:
        for queue in self._subscribers.get(event.run_id, ()):
            queue.put_nowait(event)

    def close(self, run_id: UUID) -> None:
        """Signal end-of-stream to every current subscriber."""
        for queue in self._subscribers.get(run_id, ()):
            queue.put_nowait(None)


class EventPublisher:
    """Writes run events with a monotonic per-run sequence."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        broker: EventBroker,
    ) -> None:
        self._session_factory = session_factory
        self._broker = broker

    @property
    def broker(self) -> EventBroker:
        return self._broker

    async def publish(
        self,
        run_id: UUID,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
    ) -> RunEventView:
        body = payload or {}
        last_error: IntegrityError | None = None
        for _ in range(_MAX_SEQUENCE_ATTEMPTS):
            async with self._session_factory() as session:
                sequence = await self._next_sequence(session, run_id)
                row = RunEvent(
                    run_id=run_id,
                    sequence=sequence,
                    event_type=event_type,
                    payload=body,
                )
                session.add(row)
                try:
                    await session.commit()
                except IntegrityError as exc:  # concurrent writer took the sequence
                    await session.rollback()
                    last_error = exc
                    continue

                event = RunEventView(
                    run_id=run_id,
                    sequence=sequence,
                    event_type=event_type,
                    payload=body,
                    created_at=row.created_at,
                )
                break
        else:  # pragma: no cover - only reachable under sustained contention
            raise RuntimeError(f"could not allocate run_event sequence: {last_error}")

        self._broker.publish(event)
        if event_type in TERMINAL_EVENTS:
            self._broker.close(run_id)
        return event

    async def replay(self, run_id: UUID, after_sequence: int = 0) -> list[RunEventView]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.sequence > after_sequence)
                    .order_by(RunEvent.sequence)
                )
            ).scalars()
            return [
                RunEventView(
                    run_id=row.run_id,
                    sequence=row.sequence,
                    event_type=row.event_type,
                    payload=row.payload,
                    created_at=row.created_at,
                )
                for row in rows
            ]

    @staticmethod
    async def _next_sequence(session: AsyncSession, run_id: UUID) -> int:
        current = await session.scalar(
            select(func.coalesce(func.max(RunEvent.sequence), 0)).where(
                RunEvent.run_id == run_id
            )
        )
        return int(current or 0) + 1
