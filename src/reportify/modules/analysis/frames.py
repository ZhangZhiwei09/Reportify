"""DataFrame construction and coercion helpers.

The analysis layer only ever sees a bounded sample returned by the connector; it
never re-queries and never sees more rows than the data source allows.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from reportify.modules.connectors.schemas import ColumnSchema


def frame_from_rows(rows: list[list[Any]], columns: list[ColumnSchema]) -> pd.DataFrame:
    names = [column.name for column in columns]
    frame = pd.DataFrame(rows, columns=names)
    return frame


def numeric(frame: pd.DataFrame, field: str) -> pd.Series:
    if field not in frame.columns:
        raise KeyError(field)
    return pd.to_numeric(frame[field], errors="coerce")


def timestamps(frame: pd.DataFrame, field: str) -> pd.Series:
    if field not in frame.columns:
        raise KeyError(field)
    # ``format="mixed"`` parses each value individually and avoids pandas' guess
    # warnings; invalid values become NaT and are filtered by the caller.
    converted = pd.to_datetime(frame[field], errors="coerce", utc=True, format="mixed")
    return converted


def numeric_fields(frame: pd.DataFrame, fields: list[str]) -> dict[str, pd.Series]:
    usable: dict[str, pd.Series] = {}
    for field in fields:
        if field not in frame.columns:
            continue
        series = pd.to_numeric(frame[field], errors="coerce")
        if series.notna().sum() >= 3:
            usable[field] = series
    return usable


def aggregation(agg: str) -> str:
    mapping = {"sum": "sum", "avg": "mean", "mean": "mean", "count": "count"}
    return mapping.get(agg, "sum")
