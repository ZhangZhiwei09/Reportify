"""Cron scheduler: claim due schedules and dispatch runs.

Design note (M8 Q1): the tick loop lives inside the API process. Ordering safety
does not come from the loop but from ``FOR UPDATE SKIP LOCKED`` on the schedule
row — a row already claimed by another process is simply skipped. Running several
processes stays correct; ARQ would only be needed to move the work off the API
process (see 01 §5).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.core.errors import ApiError, Conflict, InvalidArgument, NotFound
from reportify.db.models import Message, Schedule, TaskRun
from reportify.db.repositories import schedules as schedules_repo
from reportify.db.repositories import tasks as tasks_repo
from reportify.modules.runtime.runtime import AgentRuntime
from reportify.modules.runtime.schemas import RunRequest, Trigger
from reportify.modules.scheduler.cron import CronError, CronExpression, resolve_timezone
from reportify.modules.scheduler.schemas import (
    ScheduleCreate,
    ScheduleRead,
    ScheduleUpdate,
)

logger = logging.getLogger(__name__)

NAME_CHARS = 40
MAX_RUN_PAGE = 100


@dataclass(frozen=True)
class ScheduleClaim:
    """One due occurrence that this process won the right to dispatch."""

    schedule_id: UUID
    task_id: UUID
    conversation_id: UUID
    scheduled_for: datetime
    trigger: Trigger = "scheduled"


class SchedulerService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runtime: AgentRuntime,
        *,
        enabled: bool = True,
        tick_seconds: float = 15.0,
        batch_size: int = 10,
    ) -> None:
        self._session_factory = session_factory
        self._runtime = runtime
        self._enabled = enabled
        self._tick_seconds = max(1.0, float(tick_seconds))
        self._batch_size = max(1, batch_size)
        self._loop_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ CRUD

    async def create(self, payload: ScheduleCreate) -> ScheduleRead:
        expression, tz = self._parse(payload.cron, payload.timezone)
        next_run_at = self._next_run(expression, tz)
        async with self._session_factory() as session:
            task = await tasks_repo.get_task(session, payload.task_id)
            if task is None:
                raise NotFound(f"task not found: {payload.task_id}")
            name = (payload.name or task.goal[:NAME_CHARS]).strip() or "定时任务"
            try:
                schedule = await schedules_repo.create(
                    session,
                    task_id=task.id,
                    conversation_id=task.conversation_id,
                    name=name,
                    cron=payload.cron.strip(),
                    timezone=payload.timezone,
                    next_run_at=next_run_at,
                    enabled=payload.enabled,
                )
            except IntegrityError as exc:
                await session.rollback()
                raise Conflict(
                    "a schedule with the same task, cron and timezone already exists"
                ) from exc
        return self._read(schedule, 0)

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[ScheduleRead]:
        async with self._session_factory() as session:
            rows = await schedules_repo.list_schedules(
                session, limit=limit, offset=offset
            )
            counts = await schedules_repo.run_counts(session, [row.id for row in rows])
        return [self._read(row, counts.get(row.id, 0)) for row in rows]

    async def get(self, schedule_id: UUID) -> ScheduleRead:
        async with self._session_factory() as session:
            schedule = await self._require(session, schedule_id)
            counts = await schedules_repo.run_counts(session, [schedule.id])
        return self._read(schedule, counts.get(schedule.id, 0))

    async def update(
        self,
        schedule_id: UUID,
        payload: ScheduleUpdate,
    ) -> ScheduleRead:
        async with self._session_factory() as session:
            schedule = await self._require(session, schedule_id)
            reschedule = False
            if payload.cron is not None:
                schedule.cron = payload.cron.strip()
                reschedule = True
            if payload.timezone is not None:
                schedule.timezone = payload.timezone
                reschedule = True
            if payload.name is not None:
                schedule.name = payload.name.strip() or schedule.name
            if payload.enabled is not None:
                schedule.enabled = payload.enabled
                reschedule = reschedule or payload.enabled
            if reschedule:
                expression, tz = self._parse(schedule.cron, schedule.timezone)
                schedule.next_run_at = self._next_run(expression, tz)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise Conflict(
                    "a schedule with the same task, cron and timezone already exists"
                ) from exc
            await session.refresh(schedule)
            counts = await schedules_repo.run_counts(session, [schedule.id])
        return self._read(schedule, counts.get(schedule.id, 0))

    async def delete(self, schedule_id: UUID) -> None:
        async with self._session_factory() as session:
            schedule = await self._require(session, schedule_id)
            await schedules_repo.delete(session, schedule)

    async def recent_runs(self, schedule_id: UUID, *, limit: int = 20) -> list[TaskRun]:
        limit = max(1, min(limit, MAX_RUN_PAGE))
        async with self._session_factory() as session:
            await self._require(session, schedule_id)
            return list(
                await schedules_repo.recent_runs(session, schedule_id, limit=limit)
            )

    # --------------------------------------------------------------- dispatch

    async def run_now(self, schedule_id: UUID) -> UUID:
        """Dispatch one occurrence immediately (07 §6「立即运行」)."""
        async with self._session_factory() as session:
            schedule = await self._require(session, schedule_id)
            claim = ScheduleClaim(
                schedule_id=schedule.id,
                task_id=schedule.task_id,
                conversation_id=schedule.conversation_id,
                scheduled_for=datetime.now(UTC),
                trigger="api",
            )
        return await self._dispatch(claim)

    async def tick(self, *, now: datetime | None = None) -> list[UUID]:
        """Claim and dispatch everything due; returns the created run ids."""
        reference = (now or datetime.now(UTC)).astimezone(UTC)
        claims: list[ScheduleClaim] = []
        async with self._session_factory() as session:
            due = await schedules_repo.lock_due(
                session, now=reference, limit=self._batch_size
            )
            for schedule in due:
                try:
                    expression, tz = self._parse(schedule.cron, schedule.timezone)
                    following = self._next_run(expression, tz, after=reference)
                except (CronError, ApiError) as exc:
                    # A schedule that can never fire again must not spin the loop.
                    schedule.enabled = False
                    schedule.last_status = "failed"
                    schedule.last_error = {
                        "code": "invalid_cron",
                        "detail": str(exc),
                    }
                    logger.error(
                        "disabling schedule with an invalid cron expression",
                        extra={"schedule_id": str(schedule.id)},
                    )
                    continue
                claims.append(
                    ScheduleClaim(
                        schedule_id=schedule.id,
                        task_id=schedule.task_id,
                        conversation_id=schedule.conversation_id,
                        scheduled_for=schedule.next_run_at,
                    )
                )
                # Advance before dispatching: a failing dispatch must not retry
                # the same window forever.
                schedule.next_run_at = following
            await session.commit()

        run_ids: list[UUID] = []
        for claim in claims:
            try:
                run_ids.append(await self._dispatch(claim))
            except ApiError as exc:
                logger.warning(
                    "scheduled run was not dispatched",
                    extra={
                        "schedule_id": str(claim.schedule_id),
                        "code": exc.code,
                    },
                )
        return run_ids

    async def _dispatch(self, claim: ScheduleClaim) -> UUID:
        async with self._session_factory() as session:
            task = await tasks_repo.get_task(session, claim.task_id)
            if task is None:
                raise NotFound(f"task not found: {claim.task_id}")
            message = await self._latest_user_message(session, claim.task_id)
            if message is None:
                error = {
                    "code": "invalid_argument",
                    "detail": "task has no user message to run",
                }
                await schedules_repo.record_dispatch(
                    session,
                    claim.schedule_id,
                    scheduled_for=claim.scheduled_for,
                    run_id=None,
                    status="failed",
                    error=error,
                )
                raise Conflict("task has no user message to run")
            skill_names = tuple(task.skill_names or ())
            template_name = task.template_name
            conversation_id = task.conversation_id

        try:
            run_id = await self._runtime.start(
                RunRequest(
                    conversation_id=conversation_id,
                    task_id=claim.task_id,
                    user_message_id=message.id,
                    trigger=claim.trigger,
                    skill_names=skill_names,
                    template_name=template_name,
                    idempotency_key=self._idempotency_key(claim),
                    schedule_id=claim.schedule_id,
                )
            )
        except ApiError as exc:
            async with self._session_factory() as session:
                await schedules_repo.record_dispatch(
                    session,
                    claim.schedule_id,
                    scheduled_for=claim.scheduled_for,
                    run_id=None,
                    status="skipped" if exc.code == "conversation_busy" else "failed",
                    error={"code": exc.code, "detail": exc.detail},
                )
            raise

        async with self._session_factory() as session:
            await schedules_repo.record_dispatch(
                session,
                claim.schedule_id,
                scheduled_for=claim.scheduled_for,
                run_id=run_id,
                status="dispatched",
            )
        return run_id

    # ------------------------------------------------------------------- loop

    async def start(self) -> None:
        if not self._enabled or self._loop_task is not None:
            return
        self._loop_task = asyncio.create_task(self._loop(), name="scheduler-tick")

    @property
    def running(self) -> bool:
        return self._loop_task is not None and not self._loop_task.done()

    async def stop(self) -> None:
        task = self._loop_task
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._loop_task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must survive one bad tick
                logger.exception("scheduler tick failed")
            await asyncio.sleep(self._tick_seconds)

    # ---------------------------------------------------------------- helpers

    async def _require(self, session: AsyncSession, schedule_id: UUID) -> Schedule:
        schedule = await schedules_repo.get(session, schedule_id)
        if schedule is None:
            raise NotFound(f"schedule not found: {schedule_id}")
        return schedule

    async def _latest_user_message(
        self,
        session: AsyncSession,
        task_id: UUID,
    ) -> Message | None:
        return await session.scalar(
            select(Message)
            .where(Message.task_id == task_id, Message.message_type == "user_message")
            .order_by(Message.sequence.desc())
            .limit(1)
        )

    def _idempotency_key(self, claim: ScheduleClaim) -> str:
        if claim.trigger == "scheduled":
            return f"schedule:{claim.schedule_id}:{claim.scheduled_for.isoformat()}"
        return f"schedule:{claim.schedule_id}:manual:{claim.scheduled_for.isoformat()}"

    def _parse(self, cron: str, timezone: str) -> tuple[CronExpression, ZoneInfo]:
        try:
            expression = CronExpression.parse(cron)
            tz = resolve_timezone(timezone)
            # Proves the expression can actually fire, not just that it parses.
            expression.next_after(datetime.now(UTC), tz)
        except CronError as exc:
            raise InvalidArgument(str(exc)) from exc
        return expression, tz

    def _next_run(
        self,
        expression: CronExpression,
        tz: ZoneInfo,
        *,
        after: datetime | None = None,
    ) -> datetime:
        try:
            return expression.next_after(after or datetime.now(UTC), tz)
        except CronError as exc:
            raise InvalidArgument(str(exc)) from exc

    def _read(self, schedule: Schedule, run_count: int) -> ScheduleRead:
        return ScheduleRead.model_validate(schedule).model_copy(
            update={"run_count": run_count}
        )
