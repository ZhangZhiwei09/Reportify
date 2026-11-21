"""Build parameterized, read-only SELECT statements from QuerySpec."""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Dialect

from reportify.modules.connectors.errors import QueryRejected
from reportify.modules.connectors.schemas import BuiltQuery, QuerySpec

_OPERATORS = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "like": "LIKE",
}


class SafeQueryBuilder:
    """Only tables/columns from the allowlist may appear in the SQL.

    Values are always bound parameters; identifiers are quoted by the dialect.
    """

    def __init__(
        self,
        dialect: Dialect,
        tables: dict[str, set[str]],
        *,
        max_limit: int = 10_000,
    ) -> None:
        self._dialect = dialect
        self._tables = tables
        self._max_limit = max_limit

    def build(self, spec: QuerySpec) -> BuiltQuery:
        if spec.table not in self._tables:
            raise QueryRejected(f"table not allowed: {spec.table}")

        allowed_columns = self._tables[spec.table]
        if spec.limit > self._max_limit:
            raise QueryRejected(f"limit exceeds maximum of {self._max_limit}")

        select_parts: list[str] = []
        group_parts: list[str] = []

        if spec.aggregates:
            for ref in spec.group_by:
                self._require_column(ref.name, allowed_columns)
                quoted = self._quote(ref.name)
                group_parts.append(quoted)
                select_parts.append(quoted)

            for aggregate in spec.aggregates:
                if aggregate.column is not None:
                    self._require_column(aggregate.column, allowed_columns)
                    expression = f"{aggregate.func}({self._quote(aggregate.column)})"
                else:
                    expression = "count(*)"
                select_parts.append(f"{expression} AS {self._quote(aggregate.alias)}")
        else:
            for ref in spec.columns:
                self._require_column(ref.name, allowed_columns)
                select_parts.append(self._quote(ref.name))

        sql_parts = [
            "SELECT",
            "DISTINCT" if spec.distinct else "",
            ", ".join(select_parts),
            "FROM",
            self._quote_table(spec.table),
        ]
        sql = " ".join(part for part in sql_parts if part)

        params: dict[str, Any] = {}
        conditions = self._build_conditions(spec, allowed_columns, params)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        if group_parts:
            sql += " GROUP BY " + ", ".join(group_parts)

        if spec.order_by:
            order_parts: list[str] = []
            aggregate_aliases = {aggregate.alias for aggregate in spec.aggregates}
            for order in spec.order_by:
                if order.column not in allowed_columns and order.column not in aggregate_aliases:
                    raise QueryRejected(f"order column not allowed: {order.column}")
                order_parts.append(f"{self._quote(order.column)} {order.direction.upper()}")
            sql += " ORDER BY " + ", ".join(order_parts)

        sql += f" LIMIT {int(spec.limit)} OFFSET {int(spec.offset)}"
        return BuiltQuery(sql=sql, params=params)

    def _build_conditions(
        self,
        spec: QuerySpec,
        allowed_columns: set[str],
        params: dict[str, Any],
    ) -> list[str]:
        conditions: list[str] = []

        for filter_ in spec.filters:
            self._require_column(filter_.column, allowed_columns)
            column = self._quote(filter_.column)
            if filter_.op == "is_null":
                conditions.append(f"{column} IS NULL")
            elif filter_.op in {"in", "not_in"}:
                placeholders = [self._bind(params, value) for value in filter_.value]
                keyword = "IN" if filter_.op == "in" else "NOT IN"
                conditions.append(f"{column} {keyword} ({', '.join(placeholders)})")
            elif filter_.op == "between":
                low = self._bind(params, filter_.value[0])
                high = self._bind(params, filter_.value[1])
                conditions.append(f"{column} BETWEEN {low} AND {high}")
            else:
                operator = _OPERATORS[filter_.op]
                conditions.append(f"{column} {operator} {self._bind(params, filter_.value)}")

        if spec.time_range is not None:
            self._require_column(spec.time_range.column, allowed_columns)
            column = self._quote(spec.time_range.column)
            if spec.time_range.start is not None:
                conditions.append(
                    f"{column} >= {self._bind(params, spec.time_range.start)}"
                )
            if spec.time_range.end is not None:
                conditions.append(f"{column} < {self._bind(params, spec.time_range.end)}")

        return conditions

    @staticmethod
    def _require_column(name: str, allowed: set[str]) -> None:
        if name not in allowed:
            raise QueryRejected(f"column not allowed: {name}")

    def _quote(self, identifier: str) -> str:
        return self._dialect.identifier_preparer.quote(identifier)

    def _quote_table(self, table: str) -> str:
        parts = table.split(".")
        if len(parts) != 2 or not all(parts):
            raise QueryRejected("table must be schema-qualified: schema.table")
        return ".".join(self._quote(part) for part in parts)

    @staticmethod
    def _bind(params: dict[str, Any], value: Any) -> str:
        name = f"p{len(params)}"
        params[name] = value
        return f":{name}"
