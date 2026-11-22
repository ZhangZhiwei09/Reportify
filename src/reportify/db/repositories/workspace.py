"""Workspace audit persistence (08 §6.19)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from reportify.db.models import WorkspaceAudit


async def latest_hashes(session: AsyncSession) -> dict[str, str]:
    """Last recorded hash per file path, so a reload can classify changes."""
    rows = (
        await session.execute(
            select(WorkspaceAudit).order_by(WorkspaceAudit.created_at.desc()).limit(2000)
        )
    ).scalars()
    hashes: dict[str, str] = {}
    for row in rows:
        hashes.setdefault(row.file_path, row.content_hash)
    return hashes


async def write_audit(
    session: AsyncSession,
    *,
    file_path: str,
    content_hash: str,
    action: str,
    actor: str = "system",
    detail: dict[str, Any] | None = None,
) -> WorkspaceAudit:
    audit = WorkspaceAudit(
        file_path=file_path,
        content_hash=content_hash,
        action=action,
        actor=actor,
        detail=detail or {},
    )
    session.add(audit)
    await session.commit()
    await session.refresh(audit)
    return audit


async def list_audits(
    session: AsyncSession,
    *,
    limit: int = 100,
    action: str | None = None,
) -> Sequence[WorkspaceAudit]:
    query = select(WorkspaceAudit)
    if action is not None:
        query = query.where(WorkspaceAudit.action == action)
    rows = await session.execute(
        query.order_by(WorkspaceAudit.created_at.desc()).limit(limit)
    )
    return rows.scalars().all()


async def get_audit(session: AsyncSession, audit_id: UUID) -> WorkspaceAudit | None:
    return await session.get(WorkspaceAudit, audit_id)
