"""Connector request, result, lineage and profile schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

FilterOp = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "between",
    "is_null",
    "like",
]
AggregateFunc = Literal["count", "sum", "avg", "min", "max", "stddev"]
SortDirection = Literal["asc", "desc"]


class ColumnRef(BaseModel):
    name: str = Field(min_length=1)


class Filter(BaseModel):
    column: str = Field(min_length=1)
    op: FilterOp
    value: Any = None

    @model_validator(mode="after")
    def _validate_value(self) -> Filter:
        if self.op in {"in", "not_in"}:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"{self.op} requires a non-empty list")
        elif self.op == "between":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("between requires exactly two values")
        elif self.op == "is_null":
            self.value = None
        return self


class TimeRange(BaseModel):
    column: str = Field(min_length=1)
    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode="after")
    def _validate_range(self) -> TimeRange:
        if self.start is None and self.end is None:
            raise ValueError("time_range requires start or end")
        return self


class Aggregate(BaseModel):
    func: AggregateFunc
    column: str | None = None
    alias: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_column(self) -> Aggregate:
        if self.func != "count" and self.column is None:
            raise ValueError(f"{self.func} requires a column")
        return self


class OrderBy(BaseModel):
    column: str = Field(min_length=1)
    direction: SortDirection = "asc"


class QuerySpec(BaseModel):
    table: str = Field(min_length=1)
    columns: list[ColumnRef] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    time_range: TimeRange | None = None
    group_by: list[ColumnRef] = Field(default_factory=list)
    aggregates: list[Aggregate] = Field(default_factory=list)
    order_by: list[OrderBy] = Field(default_factory=list)
    distinct: bool = False
    limit: int = Field(default=1000, ge=1, le=100_000)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_shape(self) -> QuerySpec:
        if self.aggregates and self.columns:
            raise ValueError("columns cannot be combined with aggregates")
        if not self.aggregates and not self.columns:
            raise ValueError("columns or aggregates are required")
        if self.group_by and not self.aggregates:
            raise ValueError("group_by requires aggregates")
        return self


class ColumnSchema(BaseModel):
    name: str
    native_type: str
    normalized_type: str
    nullable: bool
    is_primary_key: bool = False


class TableSchema(BaseModel):
    schema_name: str
    table_name: str
    table_type: str | None = None
    row_estimate: int | None = None
    comment: str | None = None
    columns: list[ColumnSchema] = Field(default_factory=list)


class Health(BaseModel):
    ok: bool
    detail: str | None = None


class Lineage(BaseModel):
    data_source_id: UUID
    table: str | None = None
    sql: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    time_range: tuple[datetime, datetime] | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    row_count: int | None = None
    snapshot_id: UUID | None = None
    executed_at: datetime
    duration_ms: int
    definition: str = ""


class ResultSet(BaseModel):
    columns: list[ColumnSchema]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False
    lineage: Lineage
    snapshot_id: UUID


class Page(BaseModel):
    rows: list[list[Any]]
    offset: int
    limit: int
    has_more: bool


class BuiltQuery(BaseModel):
    sql: str
    params: dict[str, Any] = Field(default_factory=dict)


class ColumnProfile(BaseModel):
    name: str
    normalized_type: str
    null_ratio: float
    distinct_count: int | None = None
    min: Any | None = None
    max: Any | None = None
    mean: float | None = None
    std: float | None = None
    top_values: list[tuple[Any, int]] = Field(default_factory=list)
    sample_values: list[Any] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProfileResult(BaseModel):
    table: str
    row_count_estimate: int | None = None
    sampled_rows: int
    columns: list[ColumnProfile]
    generated_at: datetime
    lineage: Lineage
    warnings: list[str] = Field(default_factory=list)


class SyncResult(BaseModel):
    tables_added: int = 0
    tables_updated: int = 0
    columns_added: int = 0
    columns_updated: int = 0
    columns_removed: int = 0
    drifted_tables: list[str] = Field(default_factory=list)


class ColumnMetadataView(BaseModel):
    id: UUID
    column_name: str
    ordinal: int
    native_type: str
    normalized_type: str
    nullable: bool
    is_primary_key: bool
    stats: dict[str, Any] = Field(default_factory=dict)
    display_name: str | None = None
    unit: str | None = None
    description: str | None = None
    user_tags: list[str] = Field(default_factory=list)
    profile_version: int = 0


class TableMetadataView(BaseModel):
    id: UUID
    schema_name: str
    table_name: str
    table_type: str | None = None
    row_estimate: int | None = None
    comment: str | None = None
    columns: list[ColumnMetadataView] = Field(default_factory=list)
