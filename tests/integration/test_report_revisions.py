from __future__ import annotations

import uuid

from tests.support import make_send_message, text_step, tool_step, wait_for_run


def _payload(
    snapshot_id: str,
    *,
    kpi: int = 20,
    points: int = 2,
    extra_section: bool = False,
    title: str = "事件状态分布",
) -> dict:
    sections = [
        {
            "id": "overview",
            "title": "概览",
            "blocks": [
                {
                    "type": "kpi",
                    "label": "事件总数",
                    "value": kpi,
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
                            "points": [
                                {"x": f"k{index}", "y": index} for index in range(points)
                            ],
                        }
                    ],
                    "definition": "按 status 分组计数",
                    "lineage_refs": [snapshot_id],
                },
                {"type": "text", "text": "口径：全量事件。"},
            ],
        }
    ]
    if extra_section:
        sections.append(
            {
                "id": "trend",
                "title": "趋势",
                "blocks": [{"type": "text", "text": "新增趋势说明。"}],
            }
        )
    return {"title": title, "summary": "按状态统计。", "sections": sections}


def _reports_for_task(client, task_id: str) -> list[dict]:
    reports = client.get("/api/v1/reports?limit=100").json()
    return sorted(
        [item for item in reports if item["task_id"] == task_id],
        key=lambda item: item["version"],
    )


def test_two_reports_form_a_version_chain(client_factory, seeded_snapshot) -> None:
    snapshot_id = str(seeded_snapshot["snapshot_id"])

    first_client = client_factory(
        [tool_step("generate_report", {"report": _payload(snapshot_id)}), text_step("完成。")]
    )
    conversation_id = first_client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(first_client, conversation_id, "生成状态分布报告")
    assert wait_for_run(first_client, sent["run_id"])["status"] == "succeeded"
    task_id = sent["task_id"]

    # The second run reuses the previous run's ``history_blob`` (05 §9), so the
    # scripted model starts one turn in and skips index 0.
    second_client = client_factory(
        [
            text_step("unused"),
            tool_step(
                "generate_report",
                {"report": _payload(snapshot_id, kpi=25, points=3, extra_section=True)},
            ),
            text_step("完成。"),
        ]
    )
    started = second_client.post(f"/api/v1/tasks/{task_id}/runs")
    assert started.status_code == 201, started.text
    assert wait_for_run(second_client, started.json()["id"])["status"] == "succeeded"

    reports = _reports_for_task(second_client, task_id)
    assert [item["version"] for item in reports] == [1, 2]
    first, second = reports
    assert first["parent_report_id"] is None
    assert second["parent_report_id"] == first["id"]

    revisions = second_client.get(f"/api/v1/reports/{second['id']}/revisions").json()
    assert [(item["version"], item["id"]) for item in revisions] == [
        (1, first["id"]),
        (2, second["id"]),
    ]

    only_first = second_client.get(f"/api/v1/reports/{first['id']}/revisions").json()
    assert [item["id"] for item in only_first] == [first["id"]]

    diff = second_client.get(f"/api/v1/reports/{second['id']}/diff").json()
    assert diff["base_version"] == 1
    assert diff["target_version"] == 2
    assert diff["identical"] is False
    assert diff["sections_added"] == ["trend"]
    assert [(item["label"], item["before"], item["after"]) for item in diff["kpis"]] == [
        ("事件总数", 20, 25)
    ]
    assert diff["charts"][0]["points_before"] == 2
    assert diff["charts"][0]["points_after"] == 3

    explicit = second_client.get(
        f"/api/v1/reports/{second['id']}/diff",
        params={"against": first["id"]},
    ).json()
    assert explicit["kpis"] == diff["kpis"]

    # The first revision is never overwritten: its HTML is still downloadable.
    assert second_client.get(f"/api/v1/reports/{first['id']}/download").status_code == 200


def test_diff_without_parent_is_a_conflict(client_factory, seeded_snapshot) -> None:
    snapshot_id = str(seeded_snapshot["snapshot_id"])
    client = client_factory(
        [tool_step("generate_report", {"report": _payload(snapshot_id)}), text_step("完成。")]
    )
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "生成第一版")
    assert wait_for_run(client, sent["run_id"])["status"] == "succeeded"
    report = _reports_for_task(client, sent["task_id"])[0]

    response = client.get(f"/api/v1/reports/{report['id']}/diff")
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"

    unknown = client.get(
        f"/api/v1/reports/{report['id']}/diff",
        params={"against": str(uuid.uuid4())},
    )
    assert unknown.status_code == 404
