"""enforce one active run per conversation

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-22

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_task_run_active_conversation"


def upgrade() -> None:
    # 05 §7.3: one active run per conversation. Enforced by the database so the
    # guarantee holds across processes, not just inside one asyncio loop.
    op.execute(
        f"CREATE UNIQUE INDEX {INDEX_NAME} ON task_run (conversation_id) "
        "WHERE status IN ('queued', 'running', 'waiting_approval')"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
