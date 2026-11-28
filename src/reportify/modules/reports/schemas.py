"""Report Schema — the only thing the model may emit for a report.

M7 renders a self-contained HTML file with inline ECharts; the *contract* stays
what matters: every number must point at a ``dataset_snapshot`` (03 §5, 08 §6.18).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Number = int | float


class ChartPoint(BaseModel):
    x: str | Number
    y: Number | None = None


class ChartSeries(BaseModel):
    name: str = Field(min_length=1)
    points: list[ChartPoint] = Field(min_length=1)


class KpiBlock(BaseModel):
    type: Literal["kpi"]
    label: str = Field(min_length=1, max_length=200)
    value: str | Number
    unit: str | None = Field(default=None, max_length=32)
    definition: str = Field(min_length=1, max_length=500)
    lineage_refs: list[UUID] = Field(min_length=1)


class TableBlock(BaseModel):
    type: Literal["table"]
    title: str = Field(min_length=1, max_length=200)
    columns: list[str] = Field(min_length=1)
    rows: list[list[str | Number | None]] = Field(default_factory=list)
    lineage_refs: list[UUID] = Field(min_length=1)

    @model_validator(mode="after")
    def _rows_match_columns(self) -> TableBlock:
        width = len(self.columns)
        for row in self.rows:
            if len(row) != width:
                raise ValueError(f"table row has {len(row)} cells, expected {width}")
        return self


class ChartBlock(BaseModel):
    type: Literal["chart"]
    title: str = Field(min_length=1, max_length=200)
    chart_type: Literal["line", "bar", "pie", "scatter"]
    x_label: str = Field(min_length=1, max_length=120)
    y_label: str | None = Field(default=None, max_length=120)
    series: list[ChartSeries] = Field(min_length=1)
    definition: str = Field(min_length=1, max_length=500)
    lineage_refs: list[UUID] = Field(min_length=1)


class TextBlock(BaseModel):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=4000)


ReportBlock = Annotated[
    KpiBlock | TableBlock | ChartBlock | TextBlock,
    Field(discriminator="type"),
]


class ReportSection(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(min_length=1, max_length=200)
    blocks: list[ReportBlock] = Field(min_length=1)


class ReportSchema(BaseModel):
    """Validated report request. Block types are a closed set."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    template_name: str | None = Field(default=None, max_length=128)
    sections: list[ReportSection] = Field(min_length=1, max_length=20)

    @field_validator("sections")
    @classmethod
    def _unique_section_ids(cls, sections: list[ReportSection]) -> list[ReportSection]:
        seen = {section.id for section in sections}
        if len(seen) != len(sections):
            raise ValueError("section ids must be unique")
        return sections

    def lineage_refs(self) -> list[UUID]:
        refs: list[UUID] = []
        for section in self.sections:
            for block in section.blocks:
                refs.extend(getattr(block, "lineage_refs", []) or [])
        return sorted(set(refs), key=str)


class ReportRefView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    run_id: UUID
    title: str
    format: str
    storage_path: str
    content_hash: str
    status: str
    created_at: datetime
    renderer: str = "echarts-v1"
    version: int = 1
    parent_report_id: UUID | None = None
    lineage: dict[str, Any] = Field(default_factory=dict)


class ReportRevisionRead(BaseModel):
    """One node of a task's report version chain (M9)."""

    id: UUID
    version: int
    title: str
    run_id: UUID
    content_hash: str
    created_at: datetime


class KpiChange(BaseModel):
    section: str
    label: str
    before: str | Number | None = None
    after: str | Number | None = None


class ChartChange(BaseModel):
    section: str
    title: str
    series_before: int
    series_after: int
    points_before: int
    points_after: int


class TableChange(BaseModel):
    section: str
    title: str
    rows_before: int
    rows_after: int


class TextChange(BaseModel):
    section: str
    before: str
    after: str


class ReportDiff(BaseModel):
    """Structured comparison of two validated schemas."""

    base_version: int
    target_version: int
    identical: bool = True
    title_before: str | None = None
    title_after: str | None = None
    summary_before: str | None = None
    summary_after: str | None = None
    sections_added: list[str] = Field(default_factory=list)
    sections_removed: list[str] = Field(default_factory=list)
    kpis: list[KpiChange] = Field(default_factory=list)
    charts: list[ChartChange] = Field(default_factory=list)
    tables: list[TableChange] = Field(default_factory=list)
    texts: list[TextChange] = Field(default_factory=list)
