"""Discovered table and column metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reportify.db.models.base import Base, TimestampMixin


class TableMetadata(Base, TimestampMixin):
    __tablename__ = "table_metadata"
    __table_args__ = (
        UniqueConstraint(
            "data_source_id",
            "schema_name",
            "table_name",
            name="uq_table_metadata_source_schema_table",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    data_source_id: Mapped[UUID] = mapped_column(
        ForeignKey("data_source.id", ondelete="CASCADE"),
        nullable=False,
    )
    schema_name: Mapped[str] = mapped_column(String(128), nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    table_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    row_estimate: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    columns_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ColumnMetadata(Base, TimestampMixin):
    __tablename__ = "column_metadata"
    __table_args__ = (
        UniqueConstraint(
            "table_metadata_id",
            "column_name",
            name="uq_column_metadata_table_column",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    table_metadata_id: Mapped[UUID] = mapped_column(
        ForeignKey("table_metadata.id", ondelete="CASCADE"),
        nullable=False,
    )
    column_name: Mapped[str] = mapped_column(String(128), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    native_type: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_type: Mapped[str] = mapped_column(String(32), nullable=False)
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_primary_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
    )
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
