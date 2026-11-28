from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from tests.support import make_send_message, run_sql, text_step, tool_step, wait_for_run


def _args(
    data_source_id: str,
    schema: str,
    *,
    with_time: bool = True,
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "data_source_id": data_source_id,
        "table": f"{schema}.events",
    }
    if with_time:
        payload["time_column"] = "created_at"
    payload.update(overrides)
    return payload


def _run_tool(
    client_factory,
    tool: str,
    args: dict[str, Any],
    *,
    data_source,
    sync_metadata,
) -> tuple[dict, dict, Any]:
    sync_metadata(data_source.id)
    client = client_factory([tool_step(tool, args), text_step("完成。")])
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, f"调用 {tool}")
    run = wait_for_run(client, sent["run_id"], timeout=30)
    return run, sent, client


def _audit(database_url: str, run_id: str) -> dict[str, Any]:
    rows = run_sql(
        database_url,
        "SELECT tool_name, status, error_code, result_summary FROM tool_call_audit "
        "WHERE run_id = :run_id",
        run_id=run_id,
    )
    assert rows, "expected at least one tool call audit"
    return rows[0]


def test_analyze_trend_runs_and_reports_definition(
    client_factory,
    data_source,
    sync_metadata,
    sample_schema,
    database_url,
) -> None:
    args = _args(str(data_source.id), sample_schema, metric="duration", agg="avg")
    run, sent, _client = _run_tool(
        client_factory,
        "analyze_trend",
        args,
        data_source=data_source,
        sync_metadata=sync_metadata,
    )
    assert run["status"] == "succeeded", run

    audit = _audit(database_url, sent["run_id"])
    assert audit["tool_name"] == "analyze_trend"
    assert audit["status"] == "succeeded"
    summary = audit["result_summary"]["summary"]
    assert "个点" in summary


def test_analyze_distribution_tool(
    client_factory,
    data_source,
    sync_metadata,
    sample_schema,
    database_url,
) -> None:
    args = _args(
        str(data_source.id),
        sample_schema,
        with_time=False,
        field="duration",
        bins=5,
    )
    run, sent, _client = _run_tool(
        client_factory,
        "analyze_distribution",
        args,
        data_source=data_source,
        sync_metadata=sync_metadata,
    )
    assert run["status"] == "succeeded", run

    audit = _audit(database_url, sent["run_id"])
    assert audit["status"] == "succeeded"
    assert "有效值" in audit["result_summary"]["summary"]


def test_compare_periods_tool(
    client_factory,
    data_source,
    sync_metadata,
    sample_schema,
    database_url,
) -> None:
    now = datetime.now(UTC)
    args = _args(
        str(data_source.id),
        sample_schema,
        metric="duration",
        current_start=(now - timedelta(days=1)).isoformat(),
        current_end=now.isoformat(),
        previous_start=(now - timedelta(days=2)).isoformat(),
        previous_end=(now - timedelta(days=1)).isoformat(),
    )
    run, sent, _client = _run_tool(
        client_factory,
        "compare_periods",
        args,
        data_source=data_source,
        sync_metadata=sync_metadata,
    )
    assert run["status"] == "succeeded", run

    audit = _audit(database_url, sent["run_id"])
    assert audit["status"] == "succeeded"
    assert "上期" in audit["result_summary"]["summary"]


def test_detect_anomalies_tool(
    client_factory,
    data_source,
    sync_metadata,
    sample_schema,
    database_url,
) -> None:
    args = _args(str(data_source.id), sample_schema, metric="duration", method="zscore")
    run, sent, _client = _run_tool(
        client_factory,
        "detect_anomalies",
        args,
        data_source=data_source,
        sync_metadata=sync_metadata,
    )
    assert run["status"] == "succeeded", run

    audit = _audit(database_url, sent["run_id"])
    assert audit["status"] == "succeeded"
    assert "异常点" in audit["result_summary"]["summary"]


def test_analyze_correlation_tool(
    client_factory,
    data_source,
    sync_metadata,
    sample_schema,
    database_url,
) -> None:
    args = _args(
        str(data_source.id),
        sample_schema,
        with_time=False,
        fields=["duration", "id"],
        method="pearson",
    )
    run, sent, _client = _run_tool(
        client_factory,
        "analyze_correlation",
        args,
        data_source=data_source,
        sync_metadata=sync_metadata,
    )
    assert run["status"] == "succeeded", run

    audit = _audit(database_url, sent["run_id"])
    assert audit["status"] == "succeeded"
    assert "相关" in audit["result_summary"]["summary"]


def test_unknown_field_is_a_tool_failure(
    client_factory,
    data_source,
    sync_metadata,
    sample_schema,
    database_url,
) -> None:
    args = _args(str(data_source.id), sample_schema, metric="nope")
    run, sent, _client = _run_tool(
        client_factory,
        "analyze_trend",
        args,
        data_source=data_source,
        sync_metadata=sync_metadata,
    )
    assert run["status"] == "succeeded"  # the model recovers from the failure

    audit = _audit(database_url, sent["run_id"])
    assert audit["status"] == "failed"
    assert audit["error_code"] in {"invalid_argument", "upstream_error"}


def test_invalid_granularity_is_rejected_without_querying(
    client_factory,
    data_source,
    sync_metadata,
    sample_schema,
    database_url,
) -> None:
    args = _args(
        str(data_source.id),
        sample_schema,
        metric="duration",
        granularity="minute",
    )
    run, sent, _client = _run_tool(
        client_factory,
        "analyze_trend",
        args,
        data_source=data_source,
        sync_metadata=sync_metadata,
    )
    assert run["status"] == "succeeded"

    audit = _audit(database_url, sent["run_id"])
    assert audit["status"] == "failed"
    assert "granularity" in audit["result_summary"]["summary"]
