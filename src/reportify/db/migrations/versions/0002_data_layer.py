"""create data layer tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "secret",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_secret")),
        sa.UniqueConstraint("name", name=op.f("uq_secret_name")),
    )

    op.create_table(
        "data_source",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("database", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("ssl_mode", sa.String(length=16), nullable=True),
        sa.Column("secret_id", sa.Uuid(), nullable=True),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
            "status IN ('active', 'disabled', 'error')",
            name=op.f("ck_data_source_status_valid"),
        ),
        sa.CheckConstraint(
            "type IN ('postgresql', 'mysql', 'csv', 'excel', 'rest')",
            name=op.f("ck_data_source_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["secret_id"],
            ["secret.id"],
            name=op.f("fk_data_source_secret_id_secret"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_source")),
        sa.UniqueConstraint("name", name=op.f("uq_data_source_name")),
    )
    op.create_index(op.f("ix_data_source_secret_id"), "data_source", ["secret_id"])

    op.create_table(
        "table_metadata",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("schema_name", sa.String(length=128), nullable=False),
        sa.Column("table_name", sa.String(length=128), nullable=False),
        sa.Column("table_type", sa.String(length=32), nullable=True),
        sa.Column("row_estimate", sa.BigInteger(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("columns_hash", sa.String(length=64), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["data_source_id"],
            ["data_source.id"],
            name=op.f("fk_table_metadata_data_source_id_data_source"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_table_metadata")),
        sa.UniqueConstraint(
            "data_source_id",
            "schema_name",
            "table_name",
            name="uq_table_metadata_source_schema_table",
        ),
    )
    op.create_index(
        op.f("ix_table_metadata_data_source_id"),
        "table_metadata",
        ["data_source_id"],
    )

    op.create_table(
        "column_metadata",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("table_metadata_id", sa.Uuid(), nullable=False),
        sa.Column("column_name", sa.String(length=128), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("native_type", sa.String(length=128), nullable=False),
        sa.Column("normalized_type", sa.String(length=32), nullable=False),
        sa.Column("nullable", sa.Boolean(), nullable=False),
        sa.Column("is_primary_key", sa.Boolean(), nullable=False),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "user_tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("profile_version", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["table_metadata_id"],
            ["table_metadata.id"],
            name=op.f("fk_column_metadata_table_metadata_id_table_metadata"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_column_metadata")),
        sa.UniqueConstraint(
            "table_metadata_id",
            "column_name",
            name="uq_column_metadata_table_column",
        ),
    )
    op.create_index(
        op.f("ix_column_metadata_table_metadata_id"),
        "column_metadata",
        ["table_metadata_id"],
    )

    op.create_table(
        "dataset_snapshot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("table_metadata_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("query_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column(
            "columns",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "time_range",
            postgresql.TSTZRANGE(),
            nullable=True,
        ),
        sa.Column(
            "filters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
            "purpose IN ('inspect', 'profile', 'analysis', 'report')",
            name=op.f("ck_dataset_snapshot_purpose_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["data_source_id"],
            ["data_source.id"],
            name=op.f("fk_dataset_snapshot_data_source_id_data_source"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["table_metadata_id"],
            ["table_metadata.id"],
            name=op.f("fk_dataset_snapshot_table_metadata_id_table_metadata"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_snapshot")),
    )
    op.create_index(
        op.f("ix_dataset_snapshot_data_source_id"),
        "dataset_snapshot",
        ["data_source_id"],
    )
    op.create_index(
        op.f("ix_dataset_snapshot_query_fingerprint"),
        "dataset_snapshot",
        ["query_fingerprint"],
    )
    op.create_index(op.f("ix_dataset_snapshot_run_id"), "dataset_snapshot", ["run_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_dataset_snapshot_run_id"), table_name="dataset_snapshot")
    op.drop_index(
        op.f("ix_dataset_snapshot_query_fingerprint"),
        table_name="dataset_snapshot",
    )
    op.drop_index(
        op.f("ix_dataset_snapshot_data_source_id"),
        table_name="dataset_snapshot",
    )
    op.drop_table("dataset_snapshot")

    op.drop_index(
        op.f("ix_column_metadata_table_metadata_id"),
        table_name="column_metadata",
    )
    op.drop_table("column_metadata")

    op.drop_index(
        op.f("ix_table_metadata_data_source_id"),
        table_name="table_metadata",
    )
    op.drop_table("table_metadata")

    op.drop_index(op.f("ix_data_source_secret_id"), table_name="data_source")
    op.drop_table("data_source")
    op.drop_table("secret")
