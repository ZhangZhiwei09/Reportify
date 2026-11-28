"""Cron schedule persistence.

The interesting part is ``lock_due``: claiming due schedules with
``FOR UPDATE SKIP LOCKED`` is what makes a single tick safe even when several API
processes run the loop. Everything else is plain CRUD.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from reportify.db.models import Schedule, TaskRun


async def create(
    session: AsyncSession,
    *,
    task_id: UUID,
    conversation_id: UUID,
    name: str,
    cron: str,
    timezone: str,
    next_run_at: datetime,
    enabled: bool = True,
) -> Schedule:
    schedule = Schedule(
        task_id=task_id,
        conversation_id=conversation_id,
        name=name,
        cron=cron,
        timezone=timezone,
        next_run_at=next_run_at,
        enabled=enabled,
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return schedule


async def get(session: AsyncSession, schedule_id: UUID) -> Schedule | None:
    return await session.get(Schedule, schedule_id)


async def list_schedules(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[Schedule]:
    rows = await session.execute(
        select(Schedule)
        .order_by(Schedule.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return rows.scalars().all()


async def delete(session: AsyncSession, schedule: Schedule) -> None:
    await session.delete(schedule)
    await session.commit()


async def lock_due(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
) -> Sequence[Schedule]:
    """Lock enabled schedules whose next occurrence is due.

    Callers must advance ``next_run_at`` and commit; the row locks hold until
    then, so a concurrent tick skips these rows instead of double-firing.
    """
    rows = await session.execute(
        select(Schedule)
        .where(Schedule.enabled.is_(True), Schedule.next_run_at <= now)
        .order_by(Schedule.next_run_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return rows.scalars().all()


async def record_dispatch(
    session: AsyncSession,
    schedule_id: UUID,
    *,
    scheduled_for: datetime,
    run_id: UUID | None,
    status: str,
    error: dict[str, Any] | None = None,
) -> None:
    schedule = await session.get(Schedule, schedule_id)
    if schedule is None:
        return
    schedule.last_run_at = scheduled_for
    schedule.last_status = status
    schedule.last_error = error
    if run_id is not None:
        schedule.last_run_id = run_id
    await session.commit()


async def run_counts(
    session: AsyncSession,
    schedule_ids: Sequence[UUID],
) -> dict[UUID, int]:
    if not schedule_ids:
        return {}
    rows = await session.execute(
        select(TaskRun.schedule_id, func.count(TaskRun.id))
        .where(TaskRun.schedule_id.in_(list(schedule_ids)))
        .group_by(TaskRun.schedule_id)
    )
    return {schedule_id: int(count) for schedule_id, count in rows.all()}


async def recent_runs(
    session: AsyncSession,
    schedule_id: UUID,
    *,
    limit: int = 20,
) -> Sequence[TaskRun]:
    rows = await session.execute(
        select(TaskRun)
        .where(TaskRun.schedule_id == schedule_id)
        .order_by(TaskRun.created_at.desc())
        .limit(limit)
    )
    return rows.scalars().all()
