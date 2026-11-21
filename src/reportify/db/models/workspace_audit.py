"""Audit trail for workspace file loading."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reportify.db.models.base import Base, TimestampMixin


class WorkspaceAudit(Base, TimestampMixin):
    __tablename__ = "workspace_audit"
    __table_args__ = (
        CheckConstraint(
            "action IN ('loaded', 'changed', 'rejected')",
            name="action_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
