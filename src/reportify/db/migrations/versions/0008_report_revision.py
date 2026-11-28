"""add report revisions

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-28

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 05 §8: a new report never overwrites the old one. The chain is explicit so
    # revisions can be listed and diffed without re-parsing the HTML.
    op.add_column(
        "report_ref",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("report_ref", sa.Column("parent_report_id", sa.Uuid(), nullable=True))
    op.add_column(
        "report_ref",
        sa.Column(
            "schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_report_ref_parent_report_id_report_ref",
        "report_ref",
        "report_ref",
        ["parent_report_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_report_ref_task_id_version",
        "report_ref",
        ["task_id", "version"],
    )


def downgrade() -> None:
    op.drop_index("ix_report_ref_task_id_version", table_name="report_ref")
    op.drop_constraint(
        "fk_report_ref_parent_report_id_report_ref",
        "report_ref",
        type_="foreignkey",
    )
    op.drop_column("report_ref", "schema")
    op.drop_column("report_ref", "parent_report_id")
    op.drop_column("report_ref", "version")
