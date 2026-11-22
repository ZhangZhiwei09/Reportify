"""Analysis task, run instance and execution event entities."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reportify.db.models.base import Base, TimestampMixin

TASK_STATUSES = (
    "'created', 'planning', 'running', 'waiting_approval', 'completed', 'failed', 'cancelled'"
)
RUN_STATUSES = (
    "'queued', 'running', 'waiting_approval', 'succeeded', 'failed', 'cancelled', 'timed_out'"
)
RUN_TRIGGERS = "'interactive', 'scheduled', 'api'"


class AnalysisTask(Base, TimestampMixin):
    """One analysis goal; may be executed by several runs."""

    __tablename__ = "analysis_task"
    __table_args__ = (
        CheckConstraint(f"status IN ({TASK_STATUSES})", name="status_valid"),
        Index("ix_analysis_task_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("analysis_task.id", ondelete="SET NULL"),
        nullable=True,
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="created",
        server_default="created",
    )
    skill_names: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("'{}'::text[]"),
    )
    template_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    data_source_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Both forward references are created by the migration after the target
    # tables exist, hence ``use_alter``.
    current_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "task_run.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_analysis_task_current_run_id_task_run",
        ),
        nullable=True,
    )
    report_ref_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "report_ref.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_analysis_task_report_ref_id_report_ref",
        ),
        nullable=True,
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class TaskRun(Base, TimestampMixin):
    """One Agent execution instance."""

    __tablename__ = "task_run"
    __table_args__ = (
        CheckConstraint(f"status IN ({RUN_STATUSES})", name="status_valid"),
        CheckConstraint(f"trigger IN ({RUN_TRIGGERS})", name="trigger_valid"),
        Index("ix_task_run_task_id_created_at", "task_id", "created_at"),
        Index("ix_task_run_conversation_id_status", "conversation_id", "status"),
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
    trigger: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="interactive",
        server_default="interactive",
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="queued",
        server_default="queued",
    )
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    pending_approvals: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    history_blob: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class RunEvent(Base):
    """Append-only execution event stream; also the SSE replay source."""

    __tablename__ = "run_event"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('run_started', 'plan', 'model_request', 'tool_call', "
            "'tool_result', 'usage', 'approval_required', 'report_generated', "
            "'run_completed', 'error')",
            name="event_type_valid",
        ),
        UniqueConstraint("run_id", "sequence", name="uq_run_event_run_id_sequence"),
        Index("ix_run_event_run_id_created_at", "run_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("task_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
