from __future__ import annotations

import pytest

from reportify.modules.connectors.errors import MetadataNotSynced, QueryRejected
from reportify.modules.connectors.schemas import ColumnRef, QuerySpec


async def test_connection(registry, data_source) -> None:
    connector = await registry.get(data_source.id)
    health = await connector.test_connection()

    assert health.ok is True


async def test_inspect_schema(registry, data_source, sample_schema: str) -> None:
    connector = await registry.get(data_source.id)
    tables = await connector.inspect_schema()

    table = next(
        item
        for item in tables
        if item.schema_name == sample_schema and item.table_name == "events"
    )
    assert {column.name for column in table.columns} == {
        "id",
        "created_at",
        "duration",
        "status",
        "note",
    }
    assert any(column.is_primary_key for column in table.columns)
    assert next(
        column for column in table.columns if column.name == "duration"
    ).normalized_type == "numeric"


async def test_execute_requires_metadata(registry, data_source, sample_schema: str) -> None:
    connector = await registry.get(data_source.id)
    spec = QuerySpec(
        table=f"{sample_schema}.events",
        columns=[ColumnRef(name="duration")],
        limit=5,
    )

    with pytest.raises(MetadataNotSynced):
        await connector.execute(spec)


async def test_execute_and_fetch_page(
    registry,
    metadata_service,
    data_source,
    sample_schema: str,
) -> None:
    await metadata_service.sync(data_source.id)
    connector = await registry.get(data_source.id)

    spec = QuerySpec(
        table=f"{sample_schema}.events",
        columns=[ColumnRef(name="duration"), ColumnRef(name="status")],
        order_by=[{"column": "id", "direction": "asc"}],
        limit=5,
    )
    result = await connector.execute(spec)

    assert result.row_count == 5
    assert [column.name for column in result.columns] == ["duration", "status"]
    assert result.lineage.snapshot_id is not None

    page = await connector.fetch_page(result.snapshot_id, offset=0, limit=2)
    assert len(page.rows) == 2
    assert page.has_more is True


async def test_execute_rejects_unknown_table(
    registry,
    metadata_service,
    data_source,
) -> None:
    await metadata_service.sync(data_source.id)
    connector = await registry.get(data_source.id)

    with pytest.raises(QueryRejected):
        await connector.execute(
            QuerySpec(table="public.missing", columns=[ColumnRef(name="id")])
        )
