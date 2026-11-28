from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from reportify.modules.analysis import compute


def _trend_frame(days: int = 30, step: float = 1.0) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        {
            "day": (start + timedelta(days=index)).isoformat(),
            "value": index * step + 1.0,
        }
        for index in range(days)
    ]
    return pd.DataFrame(rows)


def test_trend_aggregates_and_reports_slope() -> None:
    result = compute.trend(
        _trend_frame(10, step=2.0),
        time_column="day",
        metric_column="value",
        granularity="day",
        agg="sum",
    )
    assert result.kind == "trend"
    assert result.metrics["points"] == 10
    assert result.metrics["first"] == pytest.approx(1.0)
    assert result.metrics["last"] == pytest.approx(19.0)
    assert result.metrics["change_pct"] == pytest.approx(1800.0)
    assert result.metrics["slope_per_bucket"] == pytest.approx(2.0)
    assert result.metrics["volatility"] is not None
    assert len(result.series[0].points) == 10
    assert "sum" in result.definition


def test_trend_single_bucket_warns() -> None:
    frame = _trend_frame(3)
    frame["day"] = frame["day"].str[:10]
    single = frame.head(3).copy()
    single["day"] = "2026-01-01"
    result = compute.trend(
        single,
        time_column="day",
        metric_column="value",
        granularity="day",
    )
    assert result.metrics["points"] == 1
    assert result.metrics["slope_per_bucket"] is None
    assert any("one bucket" in warning for warning in result.warnings)


def test_trend_without_valid_pairs_is_empty() -> None:
    frame = pd.DataFrame({"day": ["nope", "also-nope"], "value": [None, None]})
    result = compute.trend(
        frame,
        time_column="day",
        metric_column="value",
        granularity="day",
    )
    assert result.metrics == {}
    assert result.warnings


def test_trend_rejects_unknown_granularity() -> None:
    with pytest.raises(ValueError):
        compute.trend(
            _trend_frame(3),
            time_column="day",
            metric_column="value",
            granularity="minute",
        )


def test_distribution_numeric() -> None:
    frame = pd.DataFrame({"value": list(range(1, 101))})
    result = compute.distribution(frame, field="value", bins=10)
    assert result.kind == "distribution"
    assert result.metrics["numeric"] is True
    assert result.metrics["count"] == 100
    assert result.metrics["mean"] == pytest.approx(50.5)
    assert sum(point.y for point in result.series[0].points) == 100
    assert result.metrics["bins"] == 10


def test_distribution_categorical() -> None:
    frame = pd.DataFrame({"status": ["ok"] * 5 + ["error"] * 3 + ["skip"] * 1})
    result = compute.distribution(frame, field="status")
    assert result.metrics["numeric"] is False
    assert result.metrics["distinct_count"] == 3
    assert result.series[0].points[0].x == "ok"
    assert result.series[0].points[0].y == 5


def test_distribution_null_ratio() -> None:
    frame = pd.DataFrame({"value": [1.0, None, 3.0, None]})
    result = compute.distribution(frame, field="value")
    assert result.metrics["null_ratio"] == pytest.approx(0.5)


def test_compare_periods_computes_change() -> None:
    frame = pd.DataFrame(
        {
            "day": [
                "2026-01-01T00:00:00+00:00",
                "2026-01-02T00:00:00+00:00",
                "2026-01-08T00:00:00+00:00",
                "2026-01-09T00:00:00+00:00",
            ],
            "value": [10.0, 10.0, 30.0, 30.0],
        }
    )
    current = (datetime(2026, 1, 8, tzinfo=UTC), datetime(2026, 1, 9, tzinfo=UTC))
    previous = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))
    result = compute.compare_periods(
        frame,
        time_column="day",
        metric_column="value",
        current=current,
        previous=previous,
    )
    assert result.metrics["current"] == pytest.approx(60.0)
    assert result.metrics["previous"] == pytest.approx(20.0)
    assert result.metrics["diff"] == pytest.approx(40.0)
    assert result.metrics["change_pct"] == pytest.approx(200.0)


def test_compare_periods_missing_side_warns() -> None:
    frame = pd.DataFrame({"day": ["2026-01-08T00:00:00+00:00"], "value": [5.0]})
    result = compute.compare_periods(
        frame,
        time_column="day",
        metric_column="value",
        current=(datetime(2026, 1, 8, tzinfo=UTC), datetime(2026, 1, 9, tzinfo=UTC)),
        previous=(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)),
    )
    assert result.metrics["previous"] is None
    assert result.metrics["change_pct"] is None
    assert result.warnings


def test_detect_anomalies_zscore_finds_outlier() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    values = [10.0] * 20 + [500.0]
    frame = pd.DataFrame(
        {
            "day": [(start + timedelta(days=index)).isoformat() for index in range(len(values))],
            "value": values,
        }
    )
    result = compute.detect_anomalies(
        frame,
        time_column="day",
        metric_column="value",
        method="zscore",
        threshold=3.0,
    )
    assert result.kind == "anomaly"
    assert len(result.anomalies) == 1
    assert result.anomalies[0].value == pytest.approx(500.0)


def test_detect_anomalies_iqr() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    values = [10.0, 11.0, 12.0, 11.0, 10.0, 500.0]
    frame = pd.DataFrame(
        {
            "day": [(start + timedelta(days=index)).isoformat() for index in range(len(values))],
            "value": values,
        }
    )
    result = compute.detect_anomalies(
        frame,
        time_column="day",
        metric_column="value",
        method="iqr",
        threshold=1.5,
    )
    assert len(result.anomalies) == 1
    assert result.metrics["method"] == "iqr"


def test_detect_anomalies_constant_series_warns() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    frame = pd.DataFrame(
        {
            "day": [(start + timedelta(days=index)).isoformat() for index in range(5)],
            "value": [7.0] * 5,
        }
    )
    result = compute.detect_anomalies(
        frame,
        time_column="day",
        metric_column="value",
    )
    assert result.anomalies == []
    assert result.warnings


def test_detect_anomalies_insufficient_data() -> None:
    frame = pd.DataFrame({"day": ["2026-01-01T00:00:00+00:00"], "value": [1.0]})
    result = compute.detect_anomalies(
        frame,
        time_column="day",
        metric_column="value",
    )
    assert result.warnings
    assert result.metrics == {}


def test_correlation_perfect_relationship() -> None:
    frame = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [2.0, 4.0, 6.0, 8.0]})
    result = compute.correlation(frame, fields=["a", "b"])
    assert result.kind == "correlation"
    assert result.metrics["samples"] == 4
    assert result.metrics["matrix"]["a"]["b"] == pytest.approx(1.0)
    assert result.metrics["top_pairs"][0]["correlation"] == pytest.approx(1.0)


def test_correlation_needs_two_fields() -> None:
    frame = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    result = compute.correlation(frame, fields=["a"])
    assert result.warnings
    assert result.metrics == {}


def test_correlation_insufficient_samples() -> None:
    frame = pd.DataFrame({"a": [1.0, None], "b": [2.0, None]})
    result = compute.correlation(frame, fields=["a", "b"])
    assert result.warnings
    assert result.metrics == {}
