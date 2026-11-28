"""Long-term memory notes (08 §6.21, 02 §8 step 6)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from reportify.db.models.base import Base, TimestampMixin

MEMORY_SCOPES = "'global', 'conversation'"
MEMORY_KINDS = "'preference', 'fact', 'definition'"


class Memory(Base, TimestampMixin):
    """One durable note the agent may recall in later runs."""

    __tablename__ = "memory"
    __table_args__ = (
        CheckConstraint(f"scope IN ({MEMORY_SCOPES})", name="scope_valid"),
        CheckConstraint(f"kind IN ({MEMORY_KINDS})", name="kind_valid"),
        CheckConstraint(
            "(scope = 'global' AND scope_id IS NULL) OR "
            "(scope = 'conversation' AND scope_id IS NOT NULL)",
            name="scope_id_matches_scope",
        ),
        Index("ix_memory_scope_scope_id", "scope", "scope_id"),
        Index("ix_memory_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="fact",
        server_default="fact",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("'{}'::text[]"),
    )
    created_by: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="user",
        server_default="user",
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
