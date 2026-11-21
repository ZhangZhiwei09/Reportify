"""Deterministic column profiling."""

from __future__ import annotations

from datetime import UTC, date, datetime
from datetime import time as dt_time
from decimal import Decimal
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.db.models import ColumnMetadata, TableMetadata
from reportify.modules.connectors.base import ConnectorRegistry
from reportify.modules.connectors.errors import MetadataNotSynced, QueryRejected, TableNotFound
from reportify.modules.connectors.schemas import (
    ColumnProfile,
    ColumnRef,
    ProfileResult,
    QuerySpec,
)
from reportify.modules.connectors.types import split_table


class ProfilingService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        registry: ConnectorRegistry,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry

    async def profile(
        self,
        data_source_id: UUID,
        table: str,
        *,
        columns: list[str] | None = None,
        sample_size: int = 10_000,
    ) -> ProfileResult:
        schema_name, table_name = _split(table)
        sample_size = max(1, min(sample_size, 100_000))

        async with self._session_factory() as session:
            table_result = await session.execute(
                select(TableMetadata).where(
                    TableMetadata.data_source_id == data_source_id,
                    TableMetadata.schema_name == schema_name,
                    TableMetadata.table_name == table_name,
                )
            )
            table_meta = table_result.scalar_one_or_none()
            if table_meta is None:
                raise TableNotFound(f"table not found: {table}")

            column_models = list(
                (
                    await session.execute(
                        select(ColumnMetadata)
                        .where(ColumnMetadata.table_metadata_id == table_meta.id)
                        .order_by(ColumnMetadata.ordinal)
                    )
                ).scalars()
            )
            row_estimate = table_meta.row_estimate

        if not column_models:
            raise MetadataNotSynced(f"no columns found for table: {table}")

        by_name = {column.column_name: column for column in column_models}
        requested = columns or [column.column_name for column in column_models]
        missing = [name for name in requested if name not in by_name]
        if missing:
            raise QueryRejected(f"unknown columns: {', '.join(missing)}")

        spec = QuerySpec(
            table=table,
            columns=[ColumnRef(name=name) for name in requested],
            limit=sample_size,
        )
        connector = await self._registry.get(data_source_id)
        result = await connector.execute(
            spec,
            purpose="profile",
            max_limit=sample_size,
        )

        frame = pd.DataFrame(
            result.rows,
            columns=[column.name for column in result.columns],
        )
        profiles = [
            _profile_column(
                name,
                frame[name] if name in frame.columns else pd.Series(dtype="object"),
                by_name[name].normalized_type,
            )
            for name in requested
        ]

        warnings: list[str] = []
        if result.row_count == sample_size:
            warnings.append(f"sample limited to {sample_size} rows")

        async with self._session_factory() as session:
            async with session.begin():
                for profile in profiles:
                    column = await session.get(ColumnMetadata, by_name[profile.name].id)
                    if column is not None:
                        column.stats = profile.model_dump(mode="json", exclude={"name"})
                        column.profile_version += 1

        return ProfileResult(
            table=table,
            row_count_estimate=row_estimate,
            sampled_rows=result.row_count,
            columns=profiles,
            generated_at=datetime.now(UTC),
            lineage=result.lineage,
            warnings=warnings,
        )


def _profile_column(name: str, series: pd.Series, normalized_type: str) -> ColumnProfile:
    if len(series) == 0:
        return ColumnProfile(
            name=name,
            normalized_type=normalized_type,
            null_ratio=0.0,
            warnings=["empty column"],
        )

    non_null = series.dropna()
    warnings: list[str] = []
    if non_null.empty:
        warnings.append("all values are null")

    min_value = _safe_extreme(non_null, "min", warnings)
    max_value = _safe_extreme(non_null, "max", warnings)

    mean_value: float | None = None
    std_value: float | None = None
    if normalized_type == "numeric":
        numeric = pd.to_numeric(non_null, errors="coerce").dropna()
        if not numeric.empty:
            mean_value = float(numeric.mean())
            std_value = float(numeric.std(ddof=0))

    top_values = [
        (_scalar(index), int(count))
        for index, count in series.value_counts(dropna=True).head(20).items()
    ]
    sample_values = [_scalar(value) for value in non_null.drop_duplicates().head(20)]

    return ColumnProfile(
        name=name,
        normalized_type=normalized_type,
        null_ratio=float(series.isna().mean()),
        distinct_count=int(series.nunique(dropna=True)),
        min=min_value,
        max=max_value,
        mean=mean_value,
        std=std_value,
        top_values=top_values,
        sample_values=sample_values,
        warnings=warnings,
    )


def _safe_extreme(series: pd.Series, kind: str, warnings: list[str]):
    if series.empty:
        return None
    try:
        value = getattr(series, kind)()
    except (TypeError, ValueError):
        warnings.append(f"{kind} unavailable for mixed types")
        return None
    return _scalar(value)


def _scalar(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (AttributeError, ValueError):
            pass
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def _split(table: str) -> tuple[str, str]:
    try:
        return split_table(table)
    except ValueError as exc:
        raise QueryRejected(str(exc)) from exc
