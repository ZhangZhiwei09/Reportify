"""MCP server configuration and discovered tool cache (08 §6.14–6.15)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reportify.db.models.base import Base, TimestampMixin


class MCPServer(Base, TimestampMixin):
    """One Streamable HTTP MCP endpoint. stdio is reserved and disabled."""

    __tablename__ = "mcp_server"
    __table_args__ = (
        CheckConstraint("transport IN ('streamable_http', 'stdio')", name="transport_valid"),
        CheckConstraint("auth_type IN ('none', 'bearer', 'oauth')", name="auth_type_valid"),
        CheckConstraint(
            "status IN ('unknown', 'connected', 'error', 'disabled')",
            name="status_valid",
        ),
        CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="slug_format"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    transport: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="streamable_http",
        server_default="streamable_http",
    )
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    command: Mapped[str | None] = mapped_column(Text, nullable=True)
    args: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    cwd: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="none",
        server_default="none",
    )
    secret_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("secret.id", ondelete="RESTRICT"),
        nullable=True,
    )
    headers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocol_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    server_info: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)


class MCPToolCache(Base):
    """Discovered tool metadata. Untrusted content; never a permission source."""

    __tablename__ = "mcp_tool_cache"
    __table_args__ = (
        UniqueConstraint(
            "mcp_server_id",
            "tool_name",
            name="uq_mcp_tool_cache_mcp_server_id_tool_name",
        ),
        Index("ix_mcp_tool_cache_mcp_server_id", "mcp_server_id"),
        Index("ix_mcp_tool_cache_schema_hash", "schema_hash"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey("mcp_server.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
