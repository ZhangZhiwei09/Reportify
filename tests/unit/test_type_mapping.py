from __future__ import annotations

import pytest

from reportify.modules.connectors.types import normalize_type, split_table


@pytest.mark.parametrize(
    ("native", "expected"),
    [
        ("integer", "numeric"),
        ("numeric(12,2)", "numeric"),
        ("double precision", "numeric"),
        ("timestamptz", "temporal"),
        ("timestamp with time zone", "temporal"),
        ("date", "temporal"),
        ("boolean", "boolean"),
        ("jsonb", "json"),
        ("character varying", "text"),
        ("uuid", "text"),
        ("USER-DEFINED", "text"),
        ("bytea", "unknown"),
    ],
)
def test_normalize_type(native: str, expected: str) -> None:
    assert normalize_type(native) == expected


def test_split_table() -> None:
    assert split_table("public.events") == ("public", "events")

    with pytest.raises(ValueError):
        split_table("events")
