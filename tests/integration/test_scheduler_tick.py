from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from reportify.core.errors import ConversationBusy
from reportify.db.models import Schedule
from reportify.db.repositories import conversations as conversations_repo
from reportify.db.repositories import schedules as schedules_repo
from reportify.db.repositories import tasks as tasks_repo
from reportify.modules.runtime.schemas import RunRequest
from reportify.modules.scheduler.service import SchedulerService

# Far enough in the future that leftover rows from other tests stay dormant.
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def no_leftover_schedules(session_factory):
    """``NOW`` is fixed, so any earlier schedule would count as due."""

    async def _clear() -> None:
        async with session_factory() as session:
            await session.execute(delete(Schedule))
            await session.commit()

    await _clear()
    yield
    await _clear()


class FakeRuntime:
    """Records the request and persists a run row, like AgentRuntime.start."""

    def __init__(self, session_factory, *, busy: bool = False) -> None:
        self._session_factory = session_factory
        self._busy = busy
        self.calls: list[RunRequest] = []

    async def start(self, request: RunRequest):
        self.calls.append(request)
        if self._busy:
            raise ConversationBusy(f"busy: {request.conversation_id}")
        async with self._session_factory() as session:
            run = await tasks_repo.create_run(
                session,
                task_id=request.task_id,
                conversation_id=request.conversation_id,
                model_name="scripted",
                trigger=request.trigger,
                schedule_id=request.schedule_id,
                idempotency_key=request.idempotency_key,
            )
        return run.id


async def _seed(
    session_factory,
    *,
    cron: str = "0 * * * *",
    next_run_at: datetime,
    enabled: bool = True,
):
    async with session_factory() as session:
        conversation = await conversations_repo.create_conversation(
            session, title="定时"
        )
        task = await tasks_repo.create_task(
            session,
            conversation_id=conversation.id,
            goal="每小时分析",
        )
        await conversations_repo.append_message(
            session,
            conversation.id,
            role="user",
            message_type="user_message",
            content="每小时分析",
            task_id=task.id,
        )
        schedule = await schedules_repo.create(
            session,
            task_id=task.id,
            conversation_id=conversation.id,
            name="每小时",
            cron=cron,
            timezone="UTC",
            next_run_at=next_run_at,
            enabled=enabled,
        )
    return schedule, task


async def _reload(session_factory, schedule_id):
    async with session_factory() as session:
        return await schedules_repo.get(session, schedule_id)


async def test_tick_dispatches_once_and_advances(session_factory) -> None:
    schedule, task = await _seed(session_factory, next_run_at=NOW - timedelta(minutes=1))
    runtime = FakeRuntime(session_factory)
    service = SchedulerService(session_factory, runtime, tick_seconds=60)

    run_ids = await service.tick(now=NOW)
    assert len(run_ids) == 1
    assert len(runtime.calls) == 1
    call = runtime.calls[0]
    assert call.trigger == "scheduled"
    assert call.schedule_id == schedule.id
    assert call.task_id == task.id
    assert call.idempotency_key.startswith(f"schedule:{schedule.id}:")
    assert "2030-01-01T09:59:00" in call.idempotency_key

    reloaded = await _reload(session_factory, schedule.id)
    assert reloaded.next_run_at == datetime(2030, 1, 1, 11, 0, tzinfo=UTC)
    assert reloaded.last_status == "dispatched"
    assert reloaded.last_run_id == run_ids[0]
    assert reloaded.last_run_at == NOW - timedelta(minutes=1)

    # The same instant must not dispatch twice: next_run_at already moved on.
    assert await service.tick(now=NOW) == []


async def test_tick_ignores_paused_schedules(session_factory) -> None:
    await _seed(
        session_factory,
        next_run_at=NOW - timedelta(minutes=1),
        enabled=False,
    )
    service = SchedulerService(session_factory, FakeRuntime(session_factory))
    assert await service.tick(now=NOW) == []


async def test_tick_records_a_busy_conversation(session_factory) -> None:
    schedule, _ = await _seed(
        session_factory, next_run_at=NOW - timedelta(minutes=1)
    )
    service = SchedulerService(
        session_factory,
        FakeRuntime(session_factory, busy=True),
    )

    assert await service.tick(now=NOW) == []
    reloaded = await _reload(session_factory, schedule.id)
    assert reloaded.last_status == "skipped"
    assert reloaded.last_error["code"] == "conversation_busy"
    # Advanced anyway: a busy conversation must not hold the window forever.
    assert reloaded.next_run_at == datetime(2030, 1, 1, 11, 0, tzinfo=UTC)


async def test_tick_disables_a_never_firing_expression(session_factory) -> None:
    schedule, _ = await _seed(
        session_factory,
        cron="0 0 30 2 *",
        next_run_at=NOW - timedelta(minutes=1),
    )
    service = SchedulerService(session_factory, FakeRuntime(session_factory))

    assert await service.tick(now=NOW) == []
    reloaded = await _reload(session_factory, schedule.id)
    assert reloaded.enabled is False
    assert reloaded.last_status == "failed"
    assert reloaded.last_error["code"] == "invalid_cron"


async def test_loop_starts_only_when_enabled(session_factory) -> None:
    service = SchedulerService(
        session_factory,
        FakeRuntime(session_factory),
        tick_seconds=60,
    )
    await service.start()
    assert service.running is True
    await service.stop()
    assert service.running is False

    disabled = SchedulerService(
        session_factory,
        FakeRuntime(session_factory),
        enabled=False,
    )
    await disabled.start()
    assert disabled.running is False
    await disabled.stop()
