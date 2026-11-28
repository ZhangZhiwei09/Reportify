"""Cron schedule routes (07 §5, §6)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from reportify.api.deps import get_runtime, get_scheduler, require_auth
from reportify.modules.conversation.schemas import RunRead
from reportify.modules.runtime.runtime import AgentRuntime
from reportify.modules.scheduler.schemas import (
    ScheduleCreate,
    ScheduleRead,
    ScheduleUpdate,
)
from reportify.modules.scheduler.service import SchedulerService

router = APIRouter(
    prefix="/api/v1/schedules",
    tags=["schedules"],
    dependencies=[Depends(require_auth)],
)


@router.get("", response_model=list[ScheduleRead])
async def list_schedules(
    service: Annotated[SchedulerService, Depends(get_scheduler)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ScheduleRead]:
    return await service.list(limit=limit, offset=offset)


@router.post("", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    payload: ScheduleCreate,
    service: Annotated[SchedulerService, Depends(get_scheduler)],
) -> ScheduleRead:
    return await service.create(payload)


@router.get("/{schedule_id}", response_model=ScheduleRead)
async def get_schedule(
    schedule_id: UUID,
    service: Annotated[SchedulerService, Depends(get_scheduler)],
) -> ScheduleRead:
    return await service.get(schedule_id)


@router.patch("/{schedule_id}", response_model=ScheduleRead)
async def update_schedule(
    schedule_id: UUID,
    payload: ScheduleUpdate,
    service: Annotated[SchedulerService, Depends(get_scheduler)],
) -> ScheduleRead:
    return await service.update(schedule_id, payload)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: UUID,
    service: Annotated[SchedulerService, Depends(get_scheduler)],
) -> None:
    await service.delete(schedule_id)


@router.post(
    "/{schedule_id}/run",
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_schedule_now(
    schedule_id: UUID,
    service: Annotated[SchedulerService, Depends(get_scheduler)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> RunRead:
    run_id = await service.run_now(schedule_id)
    return RunRead.model_validate(await runtime.get_run(run_id))


@router.get("/{schedule_id}/runs", response_model=list[RunRead])
async def list_schedule_runs(
    schedule_id: UUID,
    service: Annotated[SchedulerService, Depends(get_scheduler)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[RunRead]:
    runs = await service.recent_runs(schedule_id, limit=limit)
    return [RunRead.model_validate(run) for run in runs]
