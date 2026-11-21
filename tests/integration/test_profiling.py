from __future__ import annotations


async def test_profile_writes_stats(
    metadata_service,
    profiling_service,
    data_source,
    sample_schema: str,
) -> None:
    await metadata_service.sync(data_source.id)

    result = await profiling_service.profile(
        data_source.id,
        f"{sample_schema}.events",
        sample_size=10,
    )

    assert result.sampled_rows == 10
    assert result.lineage.snapshot_id is not None

    duration = next(column for column in result.columns if column.name == "duration")
    assert duration.normalized_type == "numeric"
    assert duration.mean is not None
    assert duration.std is not None

    note = next(column for column in result.columns if column.name == "note")
    assert note.null_ratio > 0

    view = await metadata_service.get_table(
        data_source.id,
        f"{sample_schema}.events",
    )
    duration_view = next(
        column for column in view.columns if column.column_name == "duration"
    )
    assert duration_view.profile_version == 1
    assert duration_view.stats["mean"] is not None
