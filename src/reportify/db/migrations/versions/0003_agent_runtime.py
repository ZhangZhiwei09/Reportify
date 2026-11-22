"""create agent runtime tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-21

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASK_STATUSES = (
    "'created', 'planning', 'running', 'waiting_approval', 'completed', 'failed', 'cancelled'"
)
RUN_STATUSES = (
    "'queued', 'running', 'waiting_approval', 'succeeded', 'failed', 'cancelled', 'timed_out'"
)
def _timestamps() -> tuple[sa.Column, ...]:
    """Fresh timestamp columns; a Column object cannot be shared between tables."""
    return (
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
    )


def _jsonb(name: str, default: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(default),
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "conversation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("workspace_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        _jsonb("metadata", "'{}'::jsonb"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name=op.f("ck_conversation_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation")),
    )

    op.create_table(
        "analysis_task",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("parent_task_id", sa.Uuid(), nullable=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "skill_names",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("template_name", sa.String(length=128), nullable=True),
        _jsonb("data_source_refs", "'[]'::jsonb"),
        _jsonb("plan", "'{}'::jsonb"),
        sa.Column("current_run_id", sa.Uuid(), nullable=True),
        sa.Column("report_ref_id", sa.Uuid(), nullable=True),
        sa.Column(
            "error",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            f"status IN ({TASK_STATUSES})",
            name=op.f("ck_analysis_task_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name=op.f("fk_analysis_task_conversation_id_conversation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_task_id"],
            ["analysis_task.id"],
            name=op.f("fk_analysis_task_parent_task_id_analysis_task"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_task")),
    )
    op.create_index(
        "ix_analysis_task_conversation_id_created_at",
        "analysis_task",
        ["conversation_id", "created_at"],
    )
    op.create_index(op.f("ix_analysis_task_parent_task_id"), "analysis_task", ["parent_task_id"])

    op.create_table(
        "task_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        _jsonb("model_settings", "'{}'::jsonb"),
        _jsonb("limits", "'{}'::jsonb"),
        _jsonb("usage", "'{}'::jsonb"),
        sa.Column("history_blob", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            f"status IN ({RUN_STATUSES})",
            name=op.f("ck_task_run_status_valid"),
        ),
        sa.CheckConstraint(
            "trigger IN ('interactive', 'scheduled', 'api')",
            name=op.f("ck_task_run_trigger_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["analysis_task.id"],
            name=op.f("fk_task_run_task_id_analysis_task"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name=op.f("fk_task_run_conversation_id_conversation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_run")),
    )
    op.create_index("ix_task_run_task_id_created_at", "task_run", ["task_id", "created_at"])
    op.create_index(
        "ix_task_run_conversation_id_status",
        "task_run",
        ["conversation_id", "status"],
    )

    op.create_table(
        "message",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("message_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        _jsonb("payload", "'{}'::jsonb"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'tool', 'system')",
            name=op.f("ck_message_role_valid"),
        ),
        sa.CheckConstraint(
            "message_type IN ('user_message', 'assistant_message', 'tool_call', "
            "'tool_result', 'system_event', 'analysis_plan', 'report_event')",
            name=op.f("ck_message_message_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name=op.f("fk_message_conversation_id_conversation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["analysis_task.id"],
            name=op.f("fk_message_task_id_analysis_task"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["task_run.id"],
            name=op.f("fk_message_run_id_task_run"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message")),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_message_conversation_id_sequence",
        ),
    )
    op.create_index(
        "ix_message_conversation_id_created_at",
        "message",
        ["conversation_id", "created_at"],
    )
    op.create_index(op.f("ix_message_task_id"), "message", ["task_id"])
    op.create_index(op.f("ix_message_run_id"), "message", ["run_id"])

    op.create_table(
        "run_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        _jsonb("payload", "'{}'::jsonb"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('run_started', 'plan', 'model_request', 'tool_call', "
            "'tool_result', 'usage', 'approval_required', 'report_generated', "
            "'run_completed', 'error')",
            name=op.f("ck_run_event_event_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["task_run.id"],
            name=op.f("fk_run_event_run_id_task_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_event")),
        sa.UniqueConstraint("run_id", "sequence", name="uq_run_event_run_id_sequence"),
    )
    op.create_index("ix_run_event_run_id_created_at", "run_event", ["run_id", "created_at"])

    op.create_table(
        "tool_definition",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        _jsonb("input_schema", "'{}'::jsonb"),
        sa.Column("output_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("requires_approval", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("cache_version", sa.String(length=64), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('builtin_data', 'builtin_analysis', 'report', 'meta', 'mcp')",
            name=op.f("ck_tool_definition_kind_valid"),
        ),
        sa.CheckConstraint(
            "risk_level IN ('read', 'write', 'destructive')",
            name=op.f("ck_tool_definition_risk_level_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_definition")),
        sa.UniqueConstraint("name", name=op.f("uq_tool_definition_name")),
    )
    op.create_index(op.f("ix_tool_definition_source_id"), "tool_definition", ["source_id"])

    op.create_table(
        "tool_grant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tool_definition_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column("allowed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("risk_acknowledged", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("granted_by", sa.String(length=64), server_default="local", nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope IN ('global', 'conversation', 'task')",
            name=op.f("ck_tool_grant_scope_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tool_definition_id"],
            ["tool_definition.id"],
            name=op.f("fk_tool_grant_tool_definition_id_tool_definition"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_grant")),
    )
    # Global scope uses scope_id IS NULL, so plain UNIQUE would not dedupe it.
    op.execute(
        "ALTER TABLE tool_grant ADD CONSTRAINT "
        "uq_tool_grant_tool_definition_id_scope_scope_id "
        "UNIQUE NULLS NOT DISTINCT (tool_definition_id, scope, scope_id)"
    )
    op.create_index(
        op.f("ix_tool_grant_tool_definition_id"),
        "tool_grant",
        ["tool_definition_id"],
    )

    op.create_table(
        "tool_call_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("tool_definition_id", sa.Uuid(), nullable=True),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        _jsonb("arguments_redacted", "'{}'::jsonb"),
        _jsonb("result_summary", "'{}'::jsonb"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('builtin', 'mcp')",
            name=op.f("ck_tool_call_audit_source_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('allowed', 'denied', 'approved', 'rejected', 'succeeded', "
            "'failed', 'timeout')",
            name=op.f("ck_tool_call_audit_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["task_run.id"],
            name=op.f("fk_tool_call_audit_run_id_task_run"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tool_definition_id"],
            ["tool_definition.id"],
            name=op.f("fk_tool_call_audit_tool_definition_id_tool_definition"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_call_audit")),
    )
    op.create_index(
        "ix_tool_call_audit_run_id_created_at",
        "tool_call_audit",
        ["run_id", "created_at"],
    )
    op.create_index(
        "ix_tool_call_audit_tool_name_created_at",
        "tool_call_audit",
        ["tool_name", "created_at"],
    )
    op.create_index(
        op.f("ix_tool_call_audit_tool_definition_id"),
        "tool_call_audit",
        ["tool_definition_id"],
    )

    op.create_table(
        "report_ref",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("format", sa.String(length=16), server_default="html", nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        _jsonb("lineage", "'{}'::jsonb"),
        sa.Column("status", sa.String(length=16), server_default="generated", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('generated', 'failed')",
            name=op.f("ck_report_ref_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["analysis_task.id"],
            name=op.f("fk_report_ref_task_id_analysis_task"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["task_run.id"],
            name=op.f("fk_report_ref_run_id_task_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_ref")),
    )
    op.create_index("ix_report_ref_task_id_created_at", "report_ref", ["task_id", "created_at"])
    op.create_index(op.f("ix_report_ref_run_id"), "report_ref", ["run_id"])

    # Forward references closed after both sides exist.
    op.create_foreign_key(
        "fk_analysis_task_current_run_id_task_run",
        "analysis_task",
        "task_run",
        ["current_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_analysis_task_report_ref_id_report_ref",
        "analysis_task",
        "report_ref",
        ["report_ref_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_analysis_task_current_run_id"),
        "analysis_task",
        ["current_run_id"],
    )
    op.create_index(
        op.f("ix_analysis_task_report_ref_id"),
        "analysis_task",
        ["report_ref_id"],
    )

    # M1 left this column unconstrained; M2 fills the gap noted in the M1 spec.
    op.create_foreign_key(
        "fk_dataset_snapshot_run_id_task_run",
        "dataset_snapshot",
        "task_run",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_dataset_snapshot_run_id_task_run",
        "dataset_snapshot",
        type_="foreignkey",
    )

    op.drop_index(op.f("ix_analysis_task_report_ref_id"), table_name="analysis_task")
    op.drop_index(op.f("ix_analysis_task_current_run_id"), table_name="analysis_task")
    op.drop_constraint(
        "fk_analysis_task_report_ref_id_report_ref",
        "analysis_task",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_analysis_task_current_run_id_task_run",
        "analysis_task",
        type_="foreignkey",
    )

    op.drop_index(op.f("ix_report_ref_run_id"), table_name="report_ref")
    op.drop_index("ix_report_ref_task_id_created_at", table_name="report_ref")
    op.drop_table("report_ref")

    op.drop_index(
        op.f("ix_tool_call_audit_tool_definition_id"),
        table_name="tool_call_audit",
    )
    op.drop_index("ix_tool_call_audit_tool_name_created_at", table_name="tool_call_audit")
    op.drop_index("ix_tool_call_audit_run_id_created_at", table_name="tool_call_audit")
    op.drop_table("tool_call_audit")

    op.drop_index(op.f("ix_tool_grant_tool_definition_id"), table_name="tool_grant")
    op.drop_table("tool_grant")

    op.drop_index(op.f("ix_tool_definition_source_id"), table_name="tool_definition")
    op.drop_table("tool_definition")

    op.drop_index("ix_run_event_run_id_created_at", table_name="run_event")
    op.drop_table("run_event")

    op.drop_index(op.f("ix_message_run_id"), table_name="message")
    op.drop_index(op.f("ix_message_task_id"), table_name="message")
    op.drop_index("ix_message_conversation_id_created_at", table_name="message")
    op.drop_table("message")

    op.drop_index("ix_task_run_conversation_id_status", table_name="task_run")
    op.drop_index("ix_task_run_task_id_created_at", table_name="task_run")
    op.drop_table("task_run")

    op.drop_index(op.f("ix_analysis_task_parent_task_id"), table_name="analysis_task")
    op.drop_index("ix_analysis_task_conversation_id_created_at", table_name="analysis_task")
    op.drop_table("analysis_task")

    op.drop_table("conversation")
