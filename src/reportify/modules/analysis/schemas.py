"""Analysis result schema (03 §6 envelope, §5 builtin_analysis contracts)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AnalysisKind = Literal["trend", "distribution", "comparison", "anomaly", "correlation"]


class SeriesPoint(BaseModel):
    x: str
    y: float | int | None = None


class AnalysisSeries(BaseModel):
    name: str
    points: list[SeriesPoint] = Field(default_factory=list)


class AnomalyPoint(BaseModel):
    x: str
    value: float
    score: float


class AnalysisResult(BaseModel):
    """Deterministic summary produced by pandas; never raw rows."""

    kind: AnalysisKind
    summary: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    series: list[AnalysisSeries] = Field(default_factory=list)
    anomalies: list[AnomalyPoint] = Field(default_factory=list)
    definition: str = ""
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


MAX_SERIES_POINTS = 500
MAX_ANOMALIES = 100
MAX_CORRELATION_FIELDS = 20
