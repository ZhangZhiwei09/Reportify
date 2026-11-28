"""Cron schedule entity (08 §5, §12+ minimal contract)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reportify.db.models.base import Base, TimestampMixin

SCHEDULE_STATUSES = "'dispatched', 'skipped', 'failed'"


class Schedule(Base, TimestampMixin):
    """One cron trigger that re-runs an existing analysis task."""

    __tablename__ = "schedule"
    __table_args__ = (
        CheckConstraint(
            f"last_status IS NULL OR last_status IN ({SCHEDULE_STATUSES})",
            name="last_status_valid",
        ),
        UniqueConstraint("task_id", "cron", "timezone", name="task_id_cron_timezone"),
        Index("ix_schedule_enabled_next_run_at", "enabled", "next_run_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_task.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    cron: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="UTC",
        server_default="UTC",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Forward reference to task_run, created by the migration afterwards.
    last_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "task_run.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_schedule_last_run_id_task_run",
        ),
        nullable=True,
    )
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
