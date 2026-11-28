"""add long-term memory notes

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-28

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 08 §6.21: small, user-controlled notes. Retrieval is lexical (no embeddings),
    # so the table only needs the text, its scope and a timestamp.
    op.create_table(
        "memory",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            sa.String(length=16),
            server_default="fact",
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.String(length=16),
            server_default="user",
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
            "scope IN ('global', 'conversation')",
            name=op.f("ck_memory_scope_valid"),
        ),
        sa.CheckConstraint(
            "kind IN ('preference', 'fact', 'definition')",
            name=op.f("ck_memory_kind_valid"),
        ),
        sa.CheckConstraint(
            "(scope = 'global' AND scope_id IS NULL) OR "
            "(scope = 'conversation' AND scope_id IS NOT NULL)",
            name=op.f("ck_memory_scope_id_matches_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["scope_id"],
            ["conversation.id"],
            name=op.f("fk_memory_scope_id_conversation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory")),
    )
    op.create_index("ix_memory_scope_scope_id", "memory", ["scope", "scope_id"])
    op.create_index("ix_memory_created_at", "memory", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_memory_created_at", table_name="memory")
    op.drop_index("ix_memory_scope_scope_id", table_name="memory")
    op.drop_table("memory")
