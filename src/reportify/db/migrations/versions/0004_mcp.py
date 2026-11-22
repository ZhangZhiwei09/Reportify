"""create MCP server and tool cache tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-22

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_server",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column(
            "transport",
            sa.String(length=32),
            server_default="streamable_http",
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("auth_type", sa.String(length=16), server_default="none", nullable=False),
        sa.Column("secret_id", sa.Uuid(), nullable=True),
        sa.Column(
            "headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="unknown", nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("protocol_version", sa.String(length=32), nullable=True),
        sa.Column(
            "server_info",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("instructions", sa.Text(), nullable=True),
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
            "transport IN ('streamable_http', 'stdio')",
            name=op.f("ck_mcp_server_transport_valid"),
        ),
        sa.CheckConstraint(
            "auth_type IN ('none', 'bearer', 'oauth')",
            name=op.f("ck_mcp_server_auth_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('unknown', 'connected', 'error', 'disabled')",
            name=op.f("ck_mcp_server_status_valid"),
        ),
        sa.CheckConstraint("slug ~ '^[a-z0-9-]+$'", name=op.f("ck_mcp_server_slug_format")),
        sa.ForeignKeyConstraint(
            ["secret_id"],
            ["secret.id"],
            name=op.f("fk_mcp_server_secret_id_secret"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_server")),
        sa.UniqueConstraint("name", name=op.f("uq_mcp_server_name")),
        sa.UniqueConstraint("slug", name=op.f("uq_mcp_server_slug")),
    )

    op.create_table(
        "mcp_tool_cache",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mcp_server_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "input_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "annotations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["mcp_server_id"],
            ["mcp_server.id"],
            name=op.f("fk_mcp_tool_cache_mcp_server_id_mcp_server"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_tool_cache")),
        sa.UniqueConstraint(
            "mcp_server_id",
            "tool_name",
            name="uq_mcp_tool_cache_mcp_server_id_tool_name",
        ),
    )
    op.create_index(
        "ix_mcp_tool_cache_mcp_server_id",
        "mcp_tool_cache",
        ["mcp_server_id"],
    )
    op.create_index("ix_mcp_tool_cache_schema_hash", "mcp_tool_cache", ["schema_hash"])

    op.create_foreign_key(
        "fk_tool_definition_source_id_mcp_server",
        "tool_definition",
        "mcp_server",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_tool_definition_source_id_mcp_server",
        "tool_definition",
        type_="foreignkey",
    )
    op.drop_index("ix_mcp_tool_cache_schema_hash", table_name="mcp_tool_cache")
    op.drop_index("ix_mcp_tool_cache_mcp_server_id", table_name="mcp_tool_cache")
    op.drop_table("mcp_tool_cache")
    op.drop_table("mcp_server")
