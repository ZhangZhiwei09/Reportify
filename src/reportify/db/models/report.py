"""Minimal report artifact reference."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reportify.db.models.base import Base


class ReportRef(Base):
    """Reference to a generated artifact; revisions chain through ``parent_report_id``."""

    __tablename__ = "report_ref"
    __table_args__ = (
        CheckConstraint("status IN ('generated', 'failed')", name="status_valid"),
        Index("ix_report_ref_task_id_created_at", "task_id", "created_at"),
        Index("ix_report_ref_task_id_version", "task_id", "version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_task.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("task_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    format: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="html",
        server_default="html",
    )
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lineage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Validated Report Schema exactly as submitted; the diff source (M9).
    schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    parent_report_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("report_ref.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="generated",
        server_default="generated",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
