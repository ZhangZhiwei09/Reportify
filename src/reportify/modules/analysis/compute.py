"""Pure analysis functions over a sampled DataFrame (03 §5).

All statistics are computed here with pandas — the LLM only ever receives the
returned summary and a bounded number of points. Each function returns an
``AnalysisResult`` fragment; the tool layer attaches lineage.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from reportify.modules.analysis.frames import numeric, timestamps
from reportify.modules.analysis.schemas import (
    MAX_ANOMALIES,
    MAX_CORRELATION_FIELDS,
    MAX_SERIES_POINTS,
    AnalysisResult,
    AnalysisSeries,
    AnomalyPoint,
    SeriesPoint,
)

GRANULARITY_FREQ = {"hour": "h", "day": "D", "week": "W", "month": "MS"}


def _label(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def _points(series: pd.Series) -> tuple[list[SeriesPoint], bool]:
    truncated = len(series) > MAX_SERIES_POINTS
    trimmed = series.head(MAX_SERIES_POINTS)
    points = [
        SeriesPoint(x=_label(index), y=None if pd.isna(value) else float(value))
        for index, value in trimmed.items()
    ]
    return points, truncated


def trend(
    frame: pd.DataFrame,
    *,
    time_column: str,
    metric_column: str,
    granularity: str = "day",
    agg: str = "sum",
) -> AnalysisResult:
    warnings: list[str] = []
    freq = GRANULARITY_FREQ.get(granularity)
    if freq is None:
        raise ValueError(f"unsupported granularity: {granularity}")

    times = timestamps(frame, time_column)
    values = numeric(frame, metric_column)
    valid = times.notna() & values.notna()
    if not valid.any():
        return AnalysisResult(
            kind="trend",
            summary="没有可用于趋势分析的有效数据点。",
            warnings=["no valid time/value pairs"],
            definition=_definition(time_column, metric_column, granularity, agg, 0),
        )

    ordered = pd.Series(values[valid].to_numpy(), index=times[valid]).sort_index()
    aggregated = ordered.resample(freq).agg("mean" if agg in {"avg", "mean"} else agg)
    aggregated = aggregated.dropna()
    if aggregated.empty:
        return AnalysisResult(
            kind="trend",
            summary="按时间分桶后没有数据点。",
            warnings=["empty buckets"],
            definition=_definition(time_column, metric_column, granularity, agg, 0),
        )

    points, truncated = _points(aggregated)
    values_array = aggregated.to_numpy(dtype=float)
    first = float(values_array[0])
    last = float(values_array[-1])
    change_pct = None
    if first != 0:
        change_pct = (last - first) / abs(first) * 100
    slope = None
    if len(values_array) >= 2:
        slope = float(np.polyfit(np.arange(len(values_array)), values_array, 1)[0])
    volatility = None
    if len(values_array) >= 2:
        with np.errstate(divide="ignore", invalid="ignore"):
            changes = pd.Series(values_array).pct_change(fill_method=None).dropna()
        if not changes.empty:
            volatility = float(changes.std())

    if len(values_array) < 2:
        warnings.append("only one bucket: slope/volatility unavailable")

    metrics: dict[str, Any] = {
        "points": int(len(values_array)),
        "first": first,
        "last": last,
        "change_pct": change_pct,
        "slope_per_bucket": slope,
        "volatility": volatility,
        "min": float(values_array.min()),
        "max": float(values_array.max()),
        "mean": float(values_array.mean()),
    }
    summary = (
        f"按 {granularity} 聚合 {len(values_array)} 个点："
        f"从 {first:.4g} 到 {last:.4g}"
        + (f"（变化 {change_pct:+.2f}%）" if change_pct is not None else "")
        + "。"
    )
    return AnalysisResult(
        kind="trend",
        summary=summary,
        metrics=metrics,
        series=[AnalysisSeries(name=metric_column, points=points)],
        definition=_definition(time_column, metric_column, granularity, agg, len(values_array)),
        truncated=truncated,
        warnings=warnings,
    )


def distribution(
    frame: pd.DataFrame,
    *,
    field: str,
    bins: int = 10,
) -> AnalysisResult:
    warnings: list[str] = []
    if field not in frame.columns:
        raise KeyError(field)
    bins = max(2, min(bins, 50))
    raw = frame[field]
    null_ratio = float(raw.isna().mean()) if len(raw) else 0.0

    numeric_values = pd.to_numeric(raw, errors="coerce").dropna()
    if numeric_values.empty:
        counts = raw.dropna().astype(str).value_counts().head(10)
        points = [SeriesPoint(x=str(index), y=int(value)) for index, value in counts.items()]
        result = AnalysisResult(
            kind="distribution",
            summary=f"字段 {field} 无可解析数值，按类别给出 Top {len(points)}。",
            metrics={
                "distinct_count": int(raw.nunique(dropna=True)),
                "null_ratio": null_ratio,
                "numeric": False,
            },
            series=[AnalysisSeries(name=field, points=points)],
            definition=f"对 {field} 做类别频次统计（Top 10），样本 {len(raw)} 行。",
            warnings=warnings,
        )
        return result

    values = numeric_values.to_numpy(dtype=float)
    counts, edges = np.histogram(values, bins=bins)
    points = [
        SeriesPoint(
            x=f"[{edges[index]:.4g}, {edges[index + 1]:.4g})",
            y=int(counts[index]),
        )
        for index in range(len(counts))
    ]
    skew = None
    if len(values) >= 3:
        skew = float(pd.Series(values).skew())
    metrics = {
        "count": int(len(values)),
        "mean": float(values.mean()),
        "std": float(values.std(ddof=1)) if len(values) > 1 else None,
        "min": float(values.min()),
        "max": float(values.max()),
        "skew": skew,
        "null_ratio": null_ratio,
        "distinct_count": int(pd.Series(values).nunique()),
        "numeric": True,
        "bins": bins,
    }
    return AnalysisResult(
        kind="distribution",
        summary=(
            f"字段 {field} 共 {len(values)} 个有效值，"
            f"均值 {values.mean():.4g}，标准差 {metrics['std']}，偏度 {skew}。"
        ),
        metrics=metrics,
        series=[AnalysisSeries(name=field, points=points)],
        definition=f"对 {field} 做 {bins} 箱等宽直方图与描述统计，样本 {len(values)} 行。",
        warnings=warnings,
    )


def compare_periods(
    frame: pd.DataFrame,
    *,
    time_column: str,
    metric_column: str,
    current: tuple[datetime, datetime],
    previous: tuple[datetime, datetime],
    agg: str = "sum",
) -> AnalysisResult:
    warnings: list[str] = []
    times = timestamps(frame, time_column)
    values = numeric(frame, metric_column)
    valid = times.notna() & values.notna()
    if not valid.any():
        return AnalysisResult(
            kind="comparison",
            summary="没有可用于周期对比的数据点。",
            warnings=["no valid time/value pairs"],
            definition=f"比较 {metric_column} 在两个区间上的 {agg}，按 {time_column} 过滤。",
        )

    current_mask = valid & (times >= current[0]) & (times <= current[1])
    previous_mask = valid & (times >= previous[0]) & (times <= previous[1])
    current_value = _aggregate(values[current_mask], agg)
    previous_value = _aggregate(values[previous_mask], agg)

    diff = None
    change_pct = None
    if current_value is not None and previous_value is not None:
        diff = current_value - previous_value
        if previous_value != 0:
            change_pct = diff / abs(previous_value) * 100

    if current_value is None:
        warnings.append("current period has no data")
    if previous_value is None:
        warnings.append("previous period has no data")

    points = [
        SeriesPoint(x="previous", y=previous_value),
        SeriesPoint(x="current", y=current_value),
    ]
    summary = (
        f"{metric_column}：上期 {_fmt(previous_value)} → 本期 {_fmt(current_value)}"
        + (f"（{change_pct:+.2f}%）" if change_pct is not None else "")
        + "。"
    )
    return AnalysisResult(
        kind="comparison",
        summary=summary,
        metrics={
            "current": current_value,
            "previous": previous_value,
            "diff": diff,
            "change_pct": change_pct,
            "aggregation": agg,
        },
        series=[AnalysisSeries(name=metric_column, points=points)],
        definition=(
            f"{metric_column} 的 {agg}：本期 {current[0].isoformat()}–{current[1].isoformat()}，"
            f"上期 {previous[0].isoformat()}–{previous[1].isoformat()}。"
        ),
        warnings=warnings,
    )


def detect_anomalies(
    frame: pd.DataFrame,
    *,
    time_column: str,
    metric_column: str,
    method: str = "zscore",
    threshold: float = 3.0,
) -> AnalysisResult:
    warnings: list[str] = []
    times = timestamps(frame, time_column)
    values = numeric(frame, metric_column)
    valid = times.notna() & values.notna()
    if valid.sum() < 3:
        return AnalysisResult(
            kind="anomaly",
            summary="有效数据点不足 3 个，无法检测异常。",
            warnings=["insufficient data"],
            definition=f"对 {metric_column} 使用 {method} 方法，阈值 {threshold}。",
        )

    ordered = pd.Series(values[valid].to_numpy(), index=times[valid]).sort_index()
    array = ordered.to_numpy(dtype=float)
    scores = np.zeros(len(array))
    if method == "iqr":
        q1, q3 = np.percentile(array, [25, 75])
        iqr = q3 - q1
        if iqr == 0:
            warnings.append("iqr is zero: no spread to detect anomalies")
            mask = np.zeros(len(array), dtype=bool)
        else:
            lower = q1 - threshold * iqr
            upper = q3 + threshold * iqr
            mask = (array < lower) | (array > upper)
            scores = np.where(array < lower, (lower - array) / iqr, 0.0) + np.where(
                array > upper, (array - upper) / iqr, 0.0
            )
    else:
        mean = float(array.mean())
        std = float(array.std(ddof=1)) if len(array) > 1 else 0.0
        if std == 0:
            warnings.append("standard deviation is zero: no anomalies possible")
            mask = np.zeros(len(array), dtype=bool)
        else:
            scores = np.abs((array - mean) / std)
            mask = scores > threshold

    indexes = np.flatnonzero(mask)[:MAX_ANOMALIES]
    points, truncated = _points(ordered)
    anomalies = [
        AnomalyPoint(
            x=_label(ordered.index[index]),
            value=float(array[index]),
            score=float(scores[index]),
        )
        for index in indexes
    ]
    return AnalysisResult(
        kind="anomaly",
        summary=f"{metric_column} 检测到 {len(anomalies)} 个异常点（{method}，阈值 {threshold}）。",
        metrics={
            "method": method,
            "threshold": threshold,
            "count": len(anomalies),
            "points": int(len(array)),
        },
        series=[AnalysisSeries(name=metric_column, points=points)],
        anomalies=anomalies,
        definition=(
            f"对 {metric_column} 按时间排序后使用 {method} 判定异常，"
            f"阈值 {threshold}，样本 {len(array)} 点。"
        ),
        truncated=truncated,
        warnings=warnings,
    )


def correlation(
    frame: pd.DataFrame,
    *,
    fields: list[str],
    method: str = "pearson",
) -> AnalysisResult:
    warnings: list[str] = []
    usable = [field for field in fields if field in frame.columns][:MAX_CORRELATION_FIELDS]
    if len(usable) < 2:
        return AnalysisResult(
            kind="correlation",
            summary="至少需要两个数值字段才能计算相关性。",
            warnings=["need at least two numeric fields"],
            definition=f"对 {', '.join(usable) or '(none)'} 计算 {method} 相关。",
        )

    numeric_frame = pd.DataFrame(
        {field: pd.to_numeric(frame[field], errors="coerce") for field in usable}
    ).dropna()
    if len(numeric_frame) < 3:
        return AnalysisResult(
            kind="correlation",
            summary="有效样本不足 3 行，无法计算相关性。",
            warnings=["insufficient samples"],
            definition=f"对 {', '.join(usable)} 计算 {method} 相关，样本不足。",
        )

    matrix = numeric_frame.corr(method="spearman" if method == "spearman" else "pearson")
    pairs: list[dict[str, Any]] = []
    for left_index, left in enumerate(usable):
        for right in usable[left_index + 1 :]:
            value = matrix.loc[left, right]
            if pd.isna(value):
                continue
            pairs.append({"left": left, "right": right, "correlation": float(value)})
    pairs.sort(key=lambda item: abs(item["correlation"]), reverse=True)

    matrix_payload = {
        row: {
            column: (None if pd.isna(matrix.loc[row, column]) else float(matrix.loc[row, column]))
            for column in usable
        }
        for row in usable
    }
    strongest = pairs[0] if pairs else None
    summary = (
        f"{method} 相关：{len(pairs)} 对字段，最强为 "
        f"{strongest['left']} vs {strongest['right']} ({strongest['correlation']:+.3f})。"
        if strongest
        else f"{method} 相关：没有可用字段对。"
    )
    return AnalysisResult(
        kind="correlation",
        summary=summary,
        metrics={
            "method": method,
            "samples": int(len(numeric_frame)),
            "fields": usable,
            "matrix": matrix_payload,
            "top_pairs": pairs[:10],
        },
        definition=f"对 {', '.join(usable)} 计算 {method} 相关系数，样本 {len(numeric_frame)} 行。",
        warnings=warnings,
    )


def _aggregate(values: pd.Series, agg: str) -> float | None:
    if values.empty:
        return None
    if agg in {"avg", "mean"}:
        return float(values.mean())
    if agg == "count":
        return float(values.count())
    return float(values.sum())


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    if math.isnan(value):
        return "—"
    return f"{value:.4g}"


def _definition(
    time_column: str,
    metric_column: str,
    granularity: str,
    agg: str,
    points: int,
) -> str:
    return (
        f"{metric_column} 按 {time_column} 以 {granularity} 粒度分桶后取 {agg}，"
        f"共 {points} 个桶；样本来自受限只读查询。"
    )
