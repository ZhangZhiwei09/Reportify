"""Data source connection configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reportify.db.models.base import Base, TimestampMixin


class DataSource(Base, TimestampMixin):
    __tablename__ = "data_source"
    __table_args__ = (
        CheckConstraint(
            "type IN ('postgresql', 'mysql', 'csv', 'excel', 'rest')",
            name="type_valid",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled', 'error')",
            name="status_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="postgresql")

    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    database: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssl_mode: Mapped[str | None] = mapped_column(String(16), nullable=True, default="prefer")

    secret_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("secret.id", ondelete="RESTRICT"),
        nullable=True,
    )
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
