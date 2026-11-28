"""Report artifact persistence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from reportify.db.models import ReportRef


async def create_report(
    session: AsyncSession,
    *,
    task_id: UUID,
    run_id: UUID,
    title: str,
    storage_path: str,
    content_hash: str,
    lineage: dict[str, Any],
    report_id: UUID | None = None,
    status: str = "generated",
    format: str = "html",
    schema: dict[str, Any] | None = None,
    version: int = 1,
    parent_report_id: UUID | None = None,
) -> ReportRef:
    report = ReportRef(
        id=report_id or uuid4(),
        task_id=task_id,
        run_id=run_id,
        title=title,
        format=format,
        storage_path=storage_path,
        content_hash=content_hash,
        lineage=lineage,
        schema=schema,
        version=version,
        parent_report_id=parent_report_id,
        status=status,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


async def latest_for_task(session: AsyncSession, task_id: UUID) -> ReportRef | None:
    """Highest version of a task; the parent of the next revision (05 §8)."""
    return await session.scalar(
        select(ReportRef)
        .where(ReportRef.task_id == task_id)
        .order_by(ReportRef.version.desc(), ReportRef.created_at.desc())
        .limit(1)
    )


async def get_report(session: AsyncSession, report_id: UUID) -> ReportRef | None:
    return await session.get(ReportRef, report_id)


async def list_reports(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[ReportRef]:
    rows = await session.execute(
        select(ReportRef)
        .order_by(ReportRef.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return rows.scalars().all()
