"""add cron schedules

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-28

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 08 §5 increment: one cron trigger per (task, expression, timezone).
    op.create_table(
        "schedule",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("cron", sa.String(length=120), nullable=False),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default="UTC",
            nullable=False,
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.Uuid(), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column(
            "last_error",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "last_status IS NULL OR last_status IN ('dispatched', 'skipped', 'failed')",
            name=op.f("ck_schedule_last_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name=op.f("fk_schedule_conversation_id_conversation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["analysis_task.id"],
            name=op.f("fk_schedule_task_id_analysis_task"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule")),
        sa.UniqueConstraint(
            "task_id",
            "cron",
            "timezone",
            name=op.f("uq_schedule_task_id_cron_timezone"),
        ),
    )
    op.create_index(
        "ix_schedule_enabled_next_run_at",
        "schedule",
        ["enabled", "next_run_at"],
    )

    # A run remembers the schedule it came from and the key it was created with.
    op.add_column("task_run", sa.Column("schedule_id", sa.Uuid(), nullable=True))
    op.add_column(
        "task_run",
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
    )
    op.create_foreign_key(
        "fk_task_run_schedule_id_schedule",
        "task_run",
        "schedule",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_schedule_last_run_id_task_run",
        "schedule",
        "task_run",
        ["last_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_task_run_schedule_id", "task_run", ["schedule_id"])
    op.create_index(
        "uq_task_run_idempotency_key",
        "task_run",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_task_run_idempotency_key", table_name="task_run")
    op.drop_index("ix_task_run_schedule_id", table_name="task_run")
    op.drop_constraint(
        "fk_schedule_last_run_id_task_run", "schedule", type_="foreignkey"
    )
    op.drop_constraint("fk_task_run_schedule_id_schedule", "task_run", type_="foreignkey")
    op.drop_column("task_run", "idempotency_key")
    op.drop_column("task_run", "schedule_id")
    op.drop_index("ix_schedule_enabled_next_run_at", table_name="schedule")
    op.drop_table("schedule")
