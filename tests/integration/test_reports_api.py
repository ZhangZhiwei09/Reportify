from __future__ import annotations

import uuid

import pytest

from reportify.core.errors import NotFound
from reportify.modules.reports.service import ReportService
from tests.support import make_send_message, run_sql, text_step, tool_step, wait_for_run


def _report_payload(snapshot_id: str, *, title: str = "事件状态分布") -> dict:
    return {
        "title": title,
        "summary": "按状态统计事件数量。",
        "sections": [
            {
                "id": "overview",
                "title": "概览",
                "blocks": [
                    {
                        "type": "kpi",
                        "label": "事件总数",
                        "value": 20,
                        "definition": "events 表全部行数",
                        "lineage_refs": [snapshot_id],
                    },
                    {
                        "type": "chart",
                        "title": "状态分布",
                        "chart_type": "bar",
                        "x_label": "status",
                        "series": [
                            {
                                "name": "count",
                                "points": [{"x": "ok", "y": 13}, {"x": "error", "y": 7}],
                            }
                        ],
                        "definition": "按 status 分组计数",
                        "lineage_refs": [snapshot_id],
                    },
                ],
            }
        ],
    }


def test_generate_report_through_a_run(client_factory, seeded_snapshot, database_url) -> None:
    snapshot_id = str(seeded_snapshot["snapshot_id"])
    client = client_factory(
        [
            tool_step(
                "generate_report",
                {"report": _report_payload(snapshot_id)},
            ),
            text_step("报告已生成。"),
        ]
    )
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "生成状态分布报告")
    run = wait_for_run(client, sent["run_id"])
    assert run["status"] == "succeeded"

    rows = run_sql(
        database_url,
        "SELECT id, title, status, storage_path, content_hash, lineage "
        "FROM report_ref WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert len(rows) == 1
    report = rows[0]
    assert report["status"] == "generated"
    assert report["title"] == "事件状态分布"
    assert report["content_hash"]
    assert report["lineage"]["snapshot_ids"] == [snapshot_id]

    downloaded = client.get(f"/api/v1/reports/{report['id']}/download")
    assert downloaded.status_code == 200
    body = downloaded.text
    assert 'name="reportify-renderer" content="placeholder-v1"' in body
    assert "占位渲染（非最终）" in body
    assert snapshot_id in body

    listed = client.get("/api/v1/reports").json()
    assert any(item["id"] == str(report["id"]) for item in listed)

    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    assert detail["renderer"] == "placeholder-v1"
    assert detail["lineage"]["snapshot_ids"] == [snapshot_id]

    messages = client.get(f"/api/v1/conversations/{conversation_id}/messages").json()["items"]
    report_events = [item for item in messages if item["message_type"] == "report_event"]
    assert report_events
    assert report_events[0]["payload"]["report_ref_id"] == str(report["id"])

    task = client.get(f"/api/v1/tasks/{sent['task_id']}").json()
    assert task["report_ref_id"] == str(report["id"])
    assert task["status"] == "completed"


def test_unknown_snapshot_is_rejected(client_factory, database_url) -> None:
    client = client_factory(
        [
            tool_step(
                "generate_report",
                {"report": _report_payload(str(uuid.uuid4()))},
            ),
            text_step("报告生成失败。"),
        ]
    )
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "引用不存在快照")
    run = wait_for_run(client, sent["run_id"])
    assert run["status"] == "succeeded"

    reports = run_sql(
        database_url,
        "SELECT id FROM report_ref WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert reports == []

    audits = run_sql(
        database_url,
        "SELECT status, result_summary FROM tool_call_audit WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert audits[0]["status"] == "failed"
    assert "unknown dataset snapshots" in audits[0]["result_summary"]["summary"]


def test_generate_report_only_once_per_run(
    client_factory,
    seeded_snapshot,
    database_url,
) -> None:
    payload = _report_payload(str(seeded_snapshot["snapshot_id"]))
    client = client_factory(
        [
            tool_step("generate_report", {"report": payload}),
            tool_step("generate_report", {"report": {**payload, "title": "第二份"}}),
            text_step("只保留第一份。"),
        ]
    )
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "重复生成报告")
    run = wait_for_run(client, sent["run_id"])
    assert run["status"] == "succeeded"

    reports = run_sql(
        database_url,
        "SELECT id FROM report_ref WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert len(reports) == 1

    audits = run_sql(
        database_url,
        "SELECT status, result_summary FROM tool_call_audit "
        "WHERE run_id = :run_id ORDER BY created_at",
        run_id=sent["run_id"],
    )
    assert [row["status"] for row in audits] == ["succeeded", "failed"]
    assert "report_already_generated" in audits[1]["result_summary"]["summary"]


@pytest.mark.asyncio
async def test_download_refuses_path_traversal(settings) -> None:
    service = ReportService(session_factory=None, reports_dir=settings.reports_dir)  # type: ignore[arg-type]

    class FakeReport:
        storage_path = "../escape.html"

    with pytest.raises(NotFound):
        service.file_path(FakeReport())  # type: ignore[arg-type]


def test_download_unknown_report_returns_404(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get(f"/api/v1/reports/{uuid.uuid4()}/download")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
