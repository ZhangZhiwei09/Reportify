"""Tool registry, grant and audit entities."""

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
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reportify.db.models.base import Base


class ToolDefinition(Base):
    """One callable tool: builtin function or discovered MCP tool."""

    __tablename__ = "tool_definition"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('builtin_data', 'builtin_analysis', 'report', 'meta', 'mcp')",
            name="kind_valid",
        ),
        CheckConstraint(
            "risk_level IN ('read', 'write', 'destructive')",
            name="risk_level_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    # ``mcp_server`` is created by the 0004 migration (M3); the FK is declared
    # here and added there so model metadata and DDL agree.
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("mcp_server.id", ondelete="SET NULL"),
        nullable=True,
    )
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="read")
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    cache_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    discovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ToolGrant(Base):
    """Explicit allow/deny. Priority: task > conversation > global."""

    __tablename__ = "tool_grant"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('global', 'conversation', 'task')",
            name="scope_valid",
        ),
        UniqueConstraint(
            "tool_definition_id",
            "scope",
            "scope_id",
            name="uq_tool_grant_tool_definition_id_scope_scope_id",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tool_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_definition.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[UUID | None] = mapped_column(nullable=True)
    allowed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    risk_acknowledged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    granted_by: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="local",
        server_default="local",
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ToolCallAudit(Base):
    """Append-only audit. Written for every call, including denied ones."""

    __tablename__ = "tool_call_audit"
    __table_args__ = (
        CheckConstraint("source IN ('builtin', 'mcp')", name="source_valid"),
        CheckConstraint(
            "status IN ('allowed', 'denied', 'approved', 'rejected', 'succeeded', "
            "'failed', 'timeout')",
            name="status_valid",
        ),
        Index("ix_tool_call_audit_run_id_created_at", "run_id", "created_at"),
        Index("ix_tool_call_audit_tool_name_created_at", "tool_name", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("task_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_definition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tool_definition.id", ondelete="SET NULL"),
        nullable=True,
    )
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    arguments_redacted: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    result_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
