from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import dialect

from reportify.modules.connectors.errors import QueryRejected
from reportify.modules.connectors.query_builder import SafeQueryBuilder
from reportify.modules.connectors.schemas import (
    Aggregate,
    ColumnRef,
    Filter,
    OrderBy,
    QuerySpec,
)

DIALECT = dialect()
TABLES = {
    "public.events": {"id", "created_at", "duration", "status", "note"},
}


def _builder(max_limit: int = 10_000) -> SafeQueryBuilder:
    return SafeQueryBuilder(DIALECT, TABLES, max_limit=max_limit)


def test_builds_parameterized_select() -> None:
    built = _builder().build(
        QuerySpec(
            table="public.events",
            columns=[ColumnRef(name="duration")],
            filters=[Filter(column="status", op="eq", value="ok")],
            limit=10,
        )
    )

    assert "FROM public.events" in built.sql
    assert "duration" in built.sql
    assert ":p0" in built.sql
    assert "ok" not in built.sql
    assert built.params == {"p0": "ok"}
    assert built.sql.endswith("LIMIT 10 OFFSET 0")


def test_rejects_unknown_table() -> None:
    with pytest.raises(QueryRejected):
        _builder().build(
            QuerySpec(
                table="public.events; DROP TABLE users",
                columns=[ColumnRef(name="id")],
            )
        )


def test_rejects_unknown_column() -> None:
    with pytest.raises(QueryRejected):
        _builder().build(
            QuerySpec(
                table="public.events",
                columns=[ColumnRef(name="password")],
            )
        )


def test_rejects_limit_above_maximum() -> None:
    with pytest.raises(QueryRejected):
        _builder(max_limit=10).build(
            QuerySpec(
                table="public.events",
                columns=[ColumnRef(name="id")],
                limit=11,
            )
        )


def test_builds_grouped_aggregate() -> None:
    built = _builder().build(
        QuerySpec(
            table="public.events",
            aggregates=[Aggregate(func="avg", column="duration", alias="avg_duration")],
            group_by=[ColumnRef(name="status")],
            order_by=[OrderBy(column="status", direction="desc")],
        )
    )

    assert "avg(duration) AS avg_duration" in built.sql
    assert "GROUP BY status" in built.sql
    assert "ORDER BY status DESC" in built.sql


def test_requires_columns_or_aggregates() -> None:
    with pytest.raises(ValidationError):
        QuerySpec(table="public.events")
