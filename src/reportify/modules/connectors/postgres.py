"""Read-only PostgreSQL connector."""

from __future__ import annotations

import hashlib
import json
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as dt_time
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg
from sqlalchemy import Text, bindparam, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import dialect as postgres_dialect
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from reportify.db.models import ColumnMetadata, DatasetSnapshot, DataSource, TableMetadata
from reportify.modules.connectors.errors import (
    ConnectionFailed,
    DataLayerError,
    MetadataNotSynced,
    QueryTimeout,
    SnapshotNotFound,
)
from reportify.modules.connectors.query_builder import SafeQueryBuilder
from reportify.modules.connectors.schemas import (
    ColumnSchema,
    Health,
    Lineage,
    Page,
    QuerySpec,
    ResultSet,
    TableSchema,
)
from reportify.modules.connectors.types import normalize_type

_TABLES_SQL = """
SELECT
    t.table_schema,
    t.table_name,
    t.table_type,
    obj_description(
        to_regclass(format('%I.%I', t.table_schema, t.table_name)),
        'pg_class'
    ) AS comment,
    COALESCE(c.reltuples, 0)::bigint AS row_estimate
FROM information_schema.tables AS t
LEFT JOIN pg_class AS c
    ON c.oid = to_regclass(format('%I.%I', t.table_schema, t.table_name))
WHERE t.table_schema = ANY(:schemas)
  AND t.table_type IN ('BASE TABLE', 'VIEW')
ORDER BY t.table_schema, t.table_name
"""

_COLUMNS_SQL = """
SELECT table_schema, table_name, column_name, ordinal_position, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = ANY(:schemas)
ORDER BY table_schema, table_name, ordinal_position
"""

_PRIMARY_KEYS_SQL = """
SELECT tc.table_schema, tc.table_name, kcu.column_name
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
    ON tc.constraint_name = kcu.constraint_name
   AND tc.table_schema = kcu.table_schema
WHERE tc.constraint_type = 'PRIMARY KEY'
  AND tc.table_schema = ANY(:schemas)
"""


@dataclass
class _Catalog:
    allowlist: dict[str, set[str]]
    table_ids: dict[str, UUID]
    columns: dict[tuple[str, str], ColumnSchema]


class PostgresConnector:
    def __init__(
        self,
        data_source: DataSource,
        password: str,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        if not data_source.host or not data_source.database or not data_source.username:
            raise ConnectionFailed("data source is missing host, database or username")

        self._data_source = data_source
        self._session_factory = session_factory
        self._options = data_source.options or {}
        self._timeout_ms = int(self._options.get("statement_timeout_ms", 30_000))
        self._max_rows = int(self._options.get("max_rows", 10_000))
        self._schema_allowlist = list(self._options.get("schema_allowlist", ["public"]))
        self._engine = self._create_engine(password)

    def _create_engine(self, password: str) -> AsyncEngine:
        url = URL.create(
            "postgresql+asyncpg",
            username=self._data_source.username,
            password=password,
            host=self._data_source.host,
            port=self._data_source.port or 5432,
            database=self._data_source.database,
        )
        connect_args: dict[str, Any] = {
            "server_settings": {"statement_timeout": str(self._timeout_ms)}
        }
        ssl_mode = (self._data_source.ssl_mode or "prefer").lower()
        if ssl_mode == "disable":
            connect_args["ssl"] = False
        elif ssl_mode == "require":
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            connect_args["ssl"] = context
        elif ssl_mode == "verify-full":
            connect_args["ssl"] = ssl.create_default_context()

        return create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=2,
            connect_args=connect_args,
        )

    async def test_connection(self) -> Health:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            raise ConnectionFailed(_safe_error(exc)) from exc
        return Health(ok=True)

    async def inspect_schema(self) -> list[TableSchema]:
        schemas = self._schema_allowlist

        def _bind_schemas(statement: str):
            return text(statement).bindparams(bindparam("schemas", type_=ARRAY(Text)))

        try:
            async with self._engine.connect() as connection:
                table_rows = (
                    await connection.execute(
                        _bind_schemas(_TABLES_SQL),
                        {"schemas": schemas},
                    )
                ).mappings().all()
                column_rows = (
                    await connection.execute(
                        _bind_schemas(_COLUMNS_SQL),
                        {"schemas": schemas},
                    )
                ).mappings().all()
                primary_keys = (
                    await connection.execute(
                        _bind_schemas(_PRIMARY_KEYS_SQL),
                        {"schemas": schemas},
                    )
                ).mappings().all()
        except Exception as exc:
            raise ConnectionFailed(_safe_error(exc)) from exc

        pk_set = {
            (row["table_schema"], row["table_name"], row["column_name"])
            for row in primary_keys
        }

        tables: dict[tuple[str, str], TableSchema] = {}
        for row in table_rows:
            table_type = "view" if row["table_type"] == "VIEW" else "table"
            estimate = row["row_estimate"]
            tables[(row["table_schema"], row["table_name"])] = TableSchema(
                schema_name=row["table_schema"],
                table_name=row["table_name"],
                table_type=table_type,
                row_estimate=estimate if estimate is not None and estimate >= 0 else None,
                comment=row["comment"],
            )

        for row in column_rows:
            key = (row["table_schema"], row["table_name"])
            table = tables.get(key)
            if table is None:
                continue
            table.columns.append(
                ColumnSchema(
                    name=row["column_name"],
                    native_type=row["data_type"],
                    normalized_type=normalize_type(row["data_type"]),
                    nullable=row["is_nullable"] == "YES",
                    is_primary_key=(
                        row["table_schema"],
                        row["table_name"],
                        row["column_name"],
                    )
                    in pk_set,
                )
            )

        return list(tables.values())

    async def execute(
        self,
        spec: QuerySpec,
        *,
        purpose: str = "analysis",
        max_limit: int | None = None,
    ) -> ResultSet:
        catalog = await self._load_catalog()
        builder = SafeQueryBuilder(
            postgres_dialect(),
            catalog.allowlist,
            max_limit=max_limit or self._max_rows,
        )
        built = builder.build(spec)

        started = time.perf_counter()
        try:
            column_names, rows = await self._run_readonly(built.sql, built.params)
        except asyncpg.exceptions.QueryCanceledError as exc:
            raise QueryTimeout("query exceeded statement_timeout") from exc
        except asyncpg.PostgresError as exc:
            raise ConnectionFailed(_safe_error(exc)) from exc
        except Exception as exc:
            raise ConnectionFailed(_safe_error(exc)) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)

        result_columns = [
            catalog.columns.get((spec.table, name)) or self._column_schema(name)
            for name in column_names
        ]

        params_json = _jsonable(built.params)
        filters_json = _jsonable(
            {
                "filters": [item.model_dump() for item in spec.filters],
                "time_range": spec.time_range.model_dump() if spec.time_range else None,
            }
        )
        fingerprint = hashlib.sha256(
            (built.sql + json.dumps(params_json, sort_keys=True, default=str)).encode()
        ).hexdigest()

        snapshot = DatasetSnapshot(
            data_source_id=self._data_source.id,
            table_metadata_id=catalog.table_ids.get(spec.table),
            purpose=purpose,
            sql=built.sql,
            params=params_json,
            query_fingerprint=fingerprint,
            row_count=len(rows),
            columns=[column.model_dump() for column in result_columns],
            time_range=(
                func.tstzrange(spec.time_range.start, spec.time_range.end, "[]")
                if spec.time_range and spec.time_range.start and spec.time_range.end
                else None
            ),
            filters=filters_json,
        )
        async with self._session_factory() as session:
            session.add(snapshot)
            await session.commit()

        executed_at = datetime.now(UTC)
        lineage = Lineage(
            data_source_id=self._data_source.id,
            table=spec.table,
            sql=built.sql,
            params=params_json,
            time_range=(
                (spec.time_range.start, spec.time_range.end)
                if spec.time_range and spec.time_range.start and spec.time_range.end
                else None
            ),
            filters=filters_json,
            row_count=len(rows),
            snapshot_id=snapshot.id,
            executed_at=executed_at,
            duration_ms=duration_ms,
            definition=f"read-only query on {spec.table}",
        )

        return ResultSet(
            columns=result_columns,
            rows=rows,
            row_count=len(rows),
            truncated=len(rows) >= spec.limit,
            lineage=lineage,
            snapshot_id=snapshot.id,
        )

    async def fetch_page(self, snapshot_id: UUID, offset: int, limit: int) -> Page:
        if offset < 0 or limit < 1:
            raise DataLayerError("offset and limit must be positive")
        async with self._session_factory() as session:
            snapshot = await session.get(DatasetSnapshot, snapshot_id)
        if snapshot is None:
            raise SnapshotNotFound(f"snapshot not found: {snapshot_id}")

        sql = f"SELECT * FROM ({snapshot.sql.rstrip(';')}) AS _page LIMIT :_limit OFFSET :_offset"
        params = {**snapshot.params, "_limit": limit, "_offset": offset}
        _, rows = await self._run_readonly(sql, params)
        return Page(
            rows=rows,
            offset=offset,
            limit=limit,
            has_more=len(rows) == limit,
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def _run_readonly(
        self,
        sql: str,
        params: dict[str, Any],
    ) -> tuple[list[str], list[list[Any]]]:
        async with self._engine.connect() as connection:
            async with connection.begin():
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                result = await connection.execute(text(sql), params)
                column_names = list(result.keys())
                return column_names, [list(row) for row in result.fetchall()]

    async def _load_catalog(self) -> _Catalog:
        async with self._session_factory() as session:
            table_result = await session.execute(
                select(TableMetadata).where(
                    TableMetadata.data_source_id == self._data_source.id
                )
            )
            tables = list(table_result.scalars())
            if not tables:
                raise MetadataNotSynced("metadata has not been synced for this data source")

            table_ids = {
                f"{table.schema_name}.{table.table_name}": table.id for table in tables
            }
            column_result = await session.execute(
                select(ColumnMetadata).where(
                    ColumnMetadata.table_metadata_id.in_(list(table_ids.values()))
                )
            )
            columns = list(column_result.scalars())

        by_table_id = {table.id: table for table in tables}
        allowlist: dict[str, set[str]] = {}
        column_map: dict[tuple[str, str], ColumnSchema] = {}
        for table in tables:
            allowlist[f"{table.schema_name}.{table.table_name}"] = set()

        for column in columns:
            table = by_table_id.get(column.table_metadata_id)
            if table is None:
                continue
            key = f"{table.schema_name}.{table.table_name}"
            allowlist[key].add(column.column_name)
            column_map[(key, column.column_name)] = ColumnSchema(
                name=column.column_name,
                native_type=column.native_type,
                normalized_type=column.normalized_type,
                nullable=column.nullable,
                is_primary_key=column.is_primary_key,
            )

        return _Catalog(allowlist=allowlist, table_ids=table_ids, columns=column_map)

    def _column_schema(self, column: str) -> ColumnSchema:
        return ColumnSchema(
            name=column,
            native_type="unknown",
            normalized_type="unknown",
            nullable=True,
        )


def _safe_error(exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:500]


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value
