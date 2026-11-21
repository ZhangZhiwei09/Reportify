"""Query lineage snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE
from sqlalchemy.orm import Mapped, mapped_column

from reportify.db.models.base import Base, TimestampMixin


class DatasetSnapshot(Base, TimestampMixin):
    __tablename__ = "dataset_snapshot"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('inspect', 'profile', 'analysis', 'report')",
            name="purpose_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    data_source_id: Mapped[UUID] = mapped_column(
        ForeignKey("data_source.id", ondelete="CASCADE"),
        nullable=False,
    )
    table_metadata_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("table_metadata.id", ondelete="SET NULL"),
        nullable=True,
    )
    run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    query_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    columns: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    time_range: Mapped[Any | None] = mapped_column(TSTZRANGE, nullable=True)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
