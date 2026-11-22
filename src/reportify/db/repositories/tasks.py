"""Analysis task and run persistence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from reportify.db.models import AnalysisTask, TaskRun

ACTIVE_RUN_STATUSES = ("queued", "running", "waiting_approval")


async def create_task(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    goal: str,
    skill_names: Sequence[str] = (),
    template_name: str | None = None,
    parent_task_id: UUID | None = None,
) -> AnalysisTask:
    task = AnalysisTask(
        conversation_id=conversation_id,
        goal=goal,
        status="created",
        skill_names=list(skill_names),
        template_name=template_name,
        parent_task_id=parent_task_id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def get_task(session: AsyncSession, task_id: UUID) -> AnalysisTask | None:
    return await session.get(AnalysisTask, task_id)


async def list_tasks(
    session: AsyncSession,
    conversation_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[AnalysisTask]:
    rows = await session.execute(
        select(AnalysisTask)
        .where(AnalysisTask.conversation_id == conversation_id)
        .order_by(AnalysisTask.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return rows.scalars().all()


async def create_run(
    session: AsyncSession,
    *,
    task_id: UUID,
    conversation_id: UUID,
    model_name: str,
    trigger: str = "interactive",
    limits: dict[str, Any] | None = None,
    model_settings: dict[str, Any] | None = None,
) -> TaskRun:
    run = TaskRun(
        task_id=task_id,
        conversation_id=conversation_id,
        trigger=trigger,
        status="queued",
        model_name=model_name,
        limits=limits or {},
        model_settings=model_settings or {},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def get_run(session: AsyncSession, run_id: UUID) -> TaskRun | None:
    return await session.get(TaskRun, run_id)


async def active_run(session: AsyncSession, conversation_id: UUID) -> TaskRun | None:
    return await session.scalar(
        select(TaskRun)
        .where(
            TaskRun.conversation_id == conversation_id,
            TaskRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .order_by(TaskRun.created_at.desc())
        .limit(1)
    )


async def latest_run_for_task(session: AsyncSession, task_id: UUID) -> TaskRun | None:
    return await session.scalar(
        select(TaskRun)
        .where(TaskRun.task_id == task_id)
        .order_by(TaskRun.created_at.desc())
        .limit(1)
    )


async def latest_succeeded_run(session: AsyncSession, task_id: UUID) -> TaskRun | None:
    """History source for the next run in the same task (02 §8)."""
    return await session.scalar(
        select(TaskRun)
        .where(TaskRun.task_id == task_id, TaskRun.status == "succeeded")
        .order_by(TaskRun.finished_at.desc())
        .limit(1)
    )


async def mark_running(session: AsyncSession, run_id: UUID) -> None:
    run = await session.get(TaskRun, run_id)
    if run is None:
        return
    run.status = "running"
    run.started_at = run.started_at or datetime.now(UTC)
    await session.commit()


async def finish_run(
    session: AsyncSession,
    run_id: UUID,
    *,
    status: str,
    usage: dict[str, Any] | None = None,
    history_blob: list[Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    run = await session.get(TaskRun, run_id)
    if run is None:
        return
    run.status = status
    run.finished_at = datetime.now(UTC)
    if usage is not None:
        run.usage = usage
    if history_blob is not None:
        run.history_blob = history_blob
    if error is not None:
        run.error = error
    await session.commit()


async def request_cancel(session: AsyncSession, run_id: UUID) -> TaskRun | None:
    run = await session.get(TaskRun, run_id)
    if run is None:
        return None
    run.cancel_requested_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(run)
    return run


async def set_task_status(
    session: AsyncSession,
    task_id: UUID,
    *,
    status: str,
    current_run_id: UUID | None = None,
    report_ref_id: UUID | None = None,
    error: dict[str, Any] | None = None,
    completed: bool = False,
) -> None:
    task = await session.get(AnalysisTask, task_id)
    if task is None:
        return
    task.status = status
    if current_run_id is not None:
        task.current_run_id = current_run_id
    if report_ref_id is not None:
        task.report_ref_id = report_ref_id
    if error is not None:
        task.error = error
    if completed:
        task.completed_at = datetime.now(UTC)
    await session.commit()


async def stale_active_runs(
    session: AsyncSession,
    *,
    started_before: datetime,
) -> Sequence[TaskRun]:
    """Runs left behind by a crashed process (05 §9)."""
    return (
        await session.execute(
            select(TaskRun).where(
                TaskRun.status.in_(ACTIVE_RUN_STATUSES),
                TaskRun.created_at < started_before,
            )
        )
    ).scalars().all()
