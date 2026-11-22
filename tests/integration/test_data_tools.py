from __future__ import annotations

from tests.support import (
    event_names,
    make_send_message,
    run_sql,
    text_step,
    tool_step,
    wait_for_run,
)


def _query_args(data_source_id: str, schema: str, *, column: str = "status") -> dict:
    return {
        "data_source_id": data_source_id,
        "spec": {
            "table": f"{schema}.events",
            "columns": [{"name": column}],
            "limit": 5,
        },
    }


def test_query_dataset_tool_records_snapshot(
    client_factory,
    data_source,
    sync_metadata,
    sample_schema: str,
    database_url,
) -> None:
    sync_metadata(data_source.id)

    client = client_factory(
        [
            tool_step("query_dataset", _query_args(str(data_source.id), sample_schema)),
            text_step("查询完成。"),
        ]
    )
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "看几行数据")
    run = wait_for_run(client, sent["run_id"])
    assert run["status"] == "succeeded"

    audits = run_sql(
        database_url,
        "SELECT status, result_summary FROM tool_call_audit WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert audits[0]["status"] == "succeeded"
    assert audits[0]["result_summary"]["row_count"] == 5
    assert audits[0]["result_summary"]["snapshot_id"]

    snapshots = run_sql(
        database_url,
        "SELECT id, purpose, row_count, run_id FROM dataset_snapshot "
        "WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert len(snapshots) == 1
    assert str(snapshots[0]["run_id"]) == sent["run_id"]
    assert snapshots[0]["purpose"] == "analysis"


def test_query_dataset_rejects_unknown_column(
    client_factory,
    data_source,
    sync_metadata,
    sample_schema: str,
    database_url,
) -> None:
    sync_metadata(data_source.id)

    client = client_factory(
        [
            tool_step(
                "query_dataset",
                _query_args(str(data_source.id), sample_schema, column="nope"),
            ),
            text_step("列不存在。"),
        ]
    )
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "查一个不存在的列")
    run = wait_for_run(client, sent["run_id"])
    assert run["status"] == "succeeded"

    audits = run_sql(
        database_url,
        "SELECT status, error_code FROM tool_call_audit WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert audits[0]["status"] == "failed"


def test_inspect_dataset_tool(
    client_factory,
    data_source,
    sample_schema: str,
    database_url,
) -> None:
    client = client_factory(
        [
            tool_step("inspect_dataset", {"data_source_id": str(data_source.id)}),
            text_step("结构已获取。"),
        ]
    )
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "看看有哪些表")
    run = wait_for_run(client, sent["run_id"])
    assert run["status"] == "succeeded"

    audits = run_sql(
        database_url,
        "SELECT status FROM tool_call_audit WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert audits[0]["status"] == "succeeded"
    assert "tool_result" in event_names(client, sent["run_id"])
