"""Schema discovery and metadata synchronization."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.db.models import ColumnMetadata, TableMetadata
from reportify.modules.connectors.base import ConnectorRegistry
from reportify.modules.connectors.errors import (
    ColumnNotFound,
    QueryRejected,
    TableNotFound,
)
from reportify.modules.connectors.schemas import (
    ColumnMetadataView,
    ColumnSchema,
    SyncResult,
    TableMetadataView,
)
from reportify.modules.connectors.types import split_table


class MetadataService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        registry: ConnectorRegistry,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry

    async def sync(self, data_source_id: UUID) -> SyncResult:
        connector = await self._registry.get(data_source_id)
        schemas = await connector.inspect_schema()
        now = datetime.now(UTC)
        result = SyncResult()

        async with self._session_factory() as session:
            async with session.begin():
                existing_tables = list(
                    (
                        await session.execute(
                            select(TableMetadata).where(
                                TableMetadata.data_source_id == data_source_id
                            )
                        )
                    ).scalars()
                )
                by_key = {
                    (table.schema_name, table.table_name): table
                    for table in existing_tables
                }
                seen_tables: set[tuple[str, str]] = set()

                for table_schema in schemas:
                    key = (table_schema.schema_name, table_schema.table_name)
                    seen_tables.add(key)
                    columns_hash = _columns_hash(table_schema.columns)
                    table = by_key.get(key)

                    if table is None:
                        table = TableMetadata(
                            data_source_id=data_source_id,
                            schema_name=table_schema.schema_name,
                            table_name=table_schema.table_name,
                            table_type=table_schema.table_type,
                            row_estimate=table_schema.row_estimate,
                            comment=table_schema.comment,
                            columns_hash=columns_hash,
                            synced_at=now,
                        )
                        session.add(table)
                        await session.flush()
                        result.tables_added += 1
                        existing_columns: dict[str, ColumnMetadata] = {}
                    else:
                        if table.columns_hash != columns_hash:
                            result.drifted_tables.append(
                                f"{table_schema.schema_name}.{table_schema.table_name}"
                            )
                        table.table_type = table_schema.table_type
                        table.row_estimate = table_schema.row_estimate
                        table.comment = table_schema.comment
                        table.columns_hash = columns_hash
                        table.synced_at = now
                        result.tables_updated += 1
                        existing_columns = {
                            column.column_name: column
                            for column in (
                                await session.execute(
                                    select(ColumnMetadata).where(
                                        ColumnMetadata.table_metadata_id == table.id
                                    )
                                )
                            ).scalars()
                        }

                    seen_columns: set[str] = set()
                    for column in table_schema.columns:
                        seen_columns.add(column.name)
                        current = existing_columns.get(column.name)
                        if current is None:
                            session.add(
                                ColumnMetadata(
                                    table_metadata_id=table.id,
                                    column_name=column.name,
                                    ordinal=len(seen_columns),
                                    native_type=column.native_type,
                                    normalized_type=column.normalized_type,
                                    nullable=column.nullable,
                                    is_primary_key=column.is_primary_key,
                                )
                            )
                            result.columns_added += 1
                        else:
                            current.ordinal = len(seen_columns)
                            current.native_type = column.native_type
                            current.normalized_type = column.normalized_type
                            current.nullable = column.nullable
                            current.is_primary_key = column.is_primary_key
                            result.columns_updated += 1

                    for name in set(existing_columns) - seen_columns:
                        await session.delete(existing_columns[name])
                        result.columns_removed += 1

                for key, table in by_key.items():
                    if key not in seen_tables:
                        await session.delete(table)

        return result

    async def list_tables(self, data_source_id: UUID) -> list[TableMetadataView]:
        async with self._session_factory() as session:
            tables = list(
                (
                    await session.execute(
                        select(TableMetadata)
                        .where(TableMetadata.data_source_id == data_source_id)
                        .order_by(TableMetadata.schema_name, TableMetadata.table_name)
                    )
                ).scalars()
            )
            if not tables:
                return []
            columns = list(
                (
                    await session.execute(
                        select(ColumnMetadata)
                        .where(
                            ColumnMetadata.table_metadata_id.in_(
                                [table.id for table in tables]
                            )
                        )
                        .order_by(ColumnMetadata.ordinal)
                    )
                ).scalars()
            )

        by_table: dict[UUID, list[ColumnMetadata]] = {table.id: [] for table in tables}
        for column in columns:
            by_table[column.table_metadata_id].append(column)

        return [
            _table_view(table, by_table.get(table.id, []))
            for table in tables
        ]

    async def get_table(self, data_source_id: UUID, table: str) -> TableMetadataView:
        schema_name, table_name = _split(table)
        async with self._session_factory() as session:
            result = await session.execute(
                select(TableMetadata).where(
                    TableMetadata.data_source_id == data_source_id,
                    TableMetadata.schema_name == schema_name,
                    TableMetadata.table_name == table_name,
                )
            )
            table_meta = result.scalar_one_or_none()
            if table_meta is None:
                raise TableNotFound(f"table not found: {table}")
            columns = list(
                (
                    await session.execute(
                        select(ColumnMetadata)
                        .where(ColumnMetadata.table_metadata_id == table_meta.id)
                        .order_by(ColumnMetadata.ordinal)
                    )
                ).scalars()
            )
        return _table_view(table_meta, columns)

    async def update_column(
        self,
        data_source_id: UUID,
        column_id: UUID,
        *,
        display_name: str | None = None,
        unit: str | None = None,
        description: str | None = None,
        user_tags: list[str] | None = None,
        fields_set: set[str] | None = None,
    ) -> ColumnMetadataView:
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(ColumnMetadata)
                    .join(TableMetadata)
                    .where(
                        ColumnMetadata.id == column_id,
                        TableMetadata.data_source_id == data_source_id,
                    )
                )
                column = result.scalar_one_or_none()
                if column is None:
                    raise ColumnNotFound(f"column not found: {column_id}")

                fields = fields_set or set()
                if not fields or "display_name" in fields:
                    column.display_name = display_name
                if not fields or "unit" in fields:
                    column.unit = unit
                if not fields or "description" in fields:
                    column.description = description
                if not fields or "user_tags" in fields:
                    column.user_tags = user_tags or []

        return ColumnMetadataView.model_validate(column, from_attributes=True)


def _columns_hash(columns: list[ColumnSchema]) -> str:
    parts = sorted(
        f"{column.name}:{column.native_type}:{column.nullable}" for column in columns
    )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _split(table: str) -> tuple[str, str]:
    try:
        return split_table(table)
    except ValueError as exc:
        raise QueryRejected(str(exc)) from exc


def _table_view(
    table: TableMetadata,
    columns: list[ColumnMetadata],
) -> TableMetadataView:
    return TableMetadataView(
        id=table.id,
        schema_name=table.schema_name,
        table_name=table.table_name,
        table_type=table.table_type,
        row_estimate=table.row_estimate,
        comment=table.comment,
        columns=[
            ColumnMetadataView.model_validate(column, from_attributes=True)
            for column in columns
        ],
    )
