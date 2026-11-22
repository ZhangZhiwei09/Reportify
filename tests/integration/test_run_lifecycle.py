from __future__ import annotations

import uuid

from tests.support import (
    event_names,
    make_send_message,
    run_sql,
    sse_frames,
    text_step,
    tool_step,
    wait_for_run,
)


def test_full_run_produces_events_messages_and_audit(
    client_factory,
    database_url,
) -> None:
    client = client_factory(
        [
            tool_step("load_skill", {"name": "example"}),
            text_step("已按示例技能完成分析。"),
        ]
    )
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "用示例技能分析")

    run = wait_for_run(client, sent["run_id"])
    assert run["status"] == "succeeded"
    assert run["usage"]["requests"] >= 1
    assert run["error"] is None

    names = event_names(client, sent["run_id"])
    for expected in (
        "run_started",
        "plan",
        "model_request",
        "tool_call",
        "tool_result",
        "usage",
        "run_completed",
    ):
        assert expected in names, names
    assert names.index("run_started") < names.index("plan")
    assert names.index("tool_call") < names.index("tool_result")
    assert names[-1] == "run_completed"

    audits = run_sql(
        database_url,
        "SELECT tool_name, status, error_code, duration_ms FROM tool_call_audit "
        "WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert len(audits) == 1
    assert audits[0]["tool_name"] == "load_skill"
    assert audits[0]["status"] == "succeeded"
    assert audits[0]["duration_ms"] is not None

    messages = client.get(f"/api/v1/conversations/{conversation_id}/messages").json()["items"]
    types = [item["message_type"] for item in messages]
    assert "user_message" in types
    assert "analysis_plan" in types
    assert "assistant_message" in types
    assistant = next(item for item in messages if item["message_type"] == "assistant_message")
    assert assistant["content"] == "已按示例技能完成分析。"
    assert assistant["run_id"] == sent["run_id"]


def test_history_blob_is_persisted_and_reused(client_factory, database_url) -> None:
    client = client_factory([text_step("第一轮结论。"), text_step("第二轮结论。")])
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]

    first = make_send_message(client, conversation_id, "第一轮")
    wait_for_run(client, first["run_id"])
    second = make_send_message(
        client, conversation_id, "第二轮", task_id=first["task_id"]
    )
    wait_for_run(client, second["run_id"])

    rows = run_sql(
        database_url,
        "SELECT history_blob FROM task_run WHERE id = :run_id",
        run_id=second["run_id"],
    )
    blob = rows[0]["history_blob"]
    assert blob, "history_blob must be stored for the next run"
    assert isinstance(blob, list) and len(blob) >= 2


def test_sse_replay_respects_last_event_id(client_factory) -> None:
    client = client_factory([text_step("完成。")])
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "跑一次")
    wait_for_run(client, sent["run_id"])

    frames = sse_frames(client, sent["run_id"])
    assert frames
    assert [sequence for sequence, _ in frames] == sorted(sequence for sequence, _ in frames)

    cut = frames[0][0]
    tail = sse_frames(client, sent["run_id"], last_event_id=str(cut))
    assert tail
    assert all(sequence > cut for sequence, _ in tail)


def test_run_not_found(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get(f"/api/v1/runs/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_tool_failure_is_reported_as_value_not_crash(client_factory, database_url) -> None:
    client = client_factory(
        [
            tool_step("load_skill", {"name": "does-not-exist"}),
            text_step("技能不存在，改用默认方法。"),
        ]
    )
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "加载不存在的技能")

    run = wait_for_run(client, sent["run_id"])
    assert run["status"] == "succeeded"

    audits = run_sql(
        database_url,
        "SELECT status, error_code, result_summary FROM tool_call_audit "
        "WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert audits[0]["status"] == "failed"
    assert audits[0]["error_code"] == "not_found"
