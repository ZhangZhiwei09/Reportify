"""Normalize PostgreSQL types into Reportify's coarse types."""

from __future__ import annotations

_NUMERIC = {
    "smallint",
    "integer",
    "bigint",
    "decimal",
    "numeric",
    "real",
    "double precision",
    "money",
    "smallserial",
    "serial",
    "bigserial",
    "int2",
    "int4",
    "int8",
    "float4",
    "float8",
}

_TEMPORAL = {
    "date",
    "time",
    "time without time zone",
    "time with time zone",
    "timestamp",
    "timestamp without time zone",
    "timestamp with time zone",
    "timestamptz",
}

_TEXT = {
    "text",
    "character",
    "character varying",
    "varchar",
    "char",
    "uuid",
    "name",
    "citext",
    "user-defined",
}

_JSON = {"json", "jsonb"}
_BOOLEAN = {"boolean", "bool"}


def split_table(table: str) -> tuple[str, str]:
    """Split and validate a schema-qualified table name."""
    parts = table.split(".")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"table must be schema-qualified: {table}")
    return parts[0], parts[1]


def normalize_type(native_type: str) -> str:
    """Map a native type name to numeric/temporal/categorical/text/boolean/json/unknown.

    ``categorical`` is a statistical result, not a native type; the profile may
    later annotate a text column as low-cardinality.
    """
    value = native_type.strip().lower().split("(", 1)[0].strip()
    if " " in value and value.startswith(("numeric", "decimal")):
        value = value.split(" ", 1)[0]
    if value in _NUMERIC:
        return "numeric"
    if value in _TEMPORAL:
        return "temporal"
    if value in _BOOLEAN:
        return "boolean"
    if value in _JSON:
        return "json"
    if value in _TEXT:
        return "text"
    return "unknown"
