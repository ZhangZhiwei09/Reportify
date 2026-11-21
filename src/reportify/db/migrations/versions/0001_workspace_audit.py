"""create workspace_audit

Revision ID: 0001
Revises:
Create Date: 2026-11-21

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            "action IN ('loaded', 'changed', 'rejected')",
            name=op.f("ck_workspace_audit_action_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_audit")),
    )


def downgrade() -> None:
    op.drop_table("workspace_audit")
