from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def test_sync_is_idempotent(
    metadata_service,
    data_source,
    sample_schema: str,
) -> None:
    first = await metadata_service.sync(data_source.id)
    assert first.tables_added == 1
    assert first.columns_added == 5

    second = await metadata_service.sync(data_source.id)
    assert second.tables_added == 0
    assert second.tables_updated == 1
    assert second.columns_added == 0
    assert second.columns_removed == 0


async def test_sync_detects_drift(
    metadata_service,
    data_source,
    sample_schema: str,
    database_url: str,
) -> None:
    await metadata_service.sync(data_source.id)

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(f'ALTER TABLE "{sample_schema}".events ADD COLUMN extra TEXT')
            )
    finally:
        await engine.dispose()

    result = await metadata_service.sync(data_source.id)

    assert f"{sample_schema}.events" in result.drifted_tables
    assert result.columns_added == 1


async def test_get_table_returns_columns(
    metadata_service,
    data_source,
    sample_schema: str,
) -> None:
    await metadata_service.sync(data_source.id)

    table = await metadata_service.get_table(
        data_source.id,
        f"{sample_schema}.events",
    )

    assert table.table_name == "events"
    assert len(table.columns) == 5
    assert next(column for column in table.columns if column.column_name == "id").is_primary_key
