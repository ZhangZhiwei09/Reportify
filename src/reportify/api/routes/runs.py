"""Run status, event stream and cancellation."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.api.deps import get_event_publisher, get_runtime, get_session_factory, require_auth
from reportify.api.sse import parse_last_event_id, sse_response
from reportify.core.errors import NotFound
from reportify.core.events import EventPublisher
from reportify.db.repositories import tasks as tasks_repo
from reportify.modules.conversation.schemas import RunRead
from reportify.modules.runtime.runtime import AgentRuntime
from reportify.modules.runtime.schemas import ApprovalDecision

router = APIRouter(
    prefix="/api/v1/runs",
    tags=["runs"],
    dependencies=[Depends(require_auth)],
)


@router.get("/{run_id}", response_model=RunRead)
async def get_run(
    run_id: UUID,
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> RunRead:
    async with session_factory() as session:
        run = await tasks_repo.get_run(session, run_id)
    if run is None:
        raise NotFound(f"run not found: {run_id}")
    return RunRead.model_validate(run)


@router.get("/{run_id}/events")
async def stream_events(
    run_id: UUID,
    publisher: Annotated[EventPublisher, Depends(get_event_publisher)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
):
    async with session_factory() as session:
        run = await tasks_repo.get_run(session, run_id)
    if run is None:
        raise NotFound(f"run not found: {run_id}")
    return sse_response(
        publisher,
        run_id,
        after_sequence=parse_last_event_id(last_event_id),
    )


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: UUID,
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> dict[str, str]:
    run_status = await runtime.cancel(run_id)
    return {"run_id": str(run_id), "status": run_status}


@router.get("/{run_id}/approvals")
async def list_approvals(
    run_id: UUID,
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> dict[str, object]:
    approvals = await runtime.get_pending_approvals(run_id)
    return {"run_id": str(run_id), "approvals": approvals}


@router.post("/{run_id}/approvals/{approval_id}")
async def decide_approval(
    run_id: UUID,
    approval_id: str,
    payload: ApprovalDecision,
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> dict[str, object]:
    return await runtime.decide(
        run_id,
        approval_id,
        approved=payload.decision == "approve",
    )
