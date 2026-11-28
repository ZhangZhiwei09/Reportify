from __future__ import annotations

import time

from reportify.modules.tools.schemas import ToolSpec
from tests.support import execute_sql, make_send_message, run_sql, wait_for_run


def test_loop_dispatches_a_due_schedule(client_factory, settings, database_url) -> None:
    loop_settings = settings.model_copy(
        update={"scheduler_enabled": True, "scheduler_tick_seconds": 1.0}
    )
    client = client_factory([], settings_override=loop_settings)
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "每小时的活跃用户分析")
    assert wait_for_run(client, sent["run_id"])["status"] == "succeeded"

    schedule = client.post(
        "/api/v1/schedules",
        json={"task_id": sent["task_id"], "cron": "0 9 * * *"},
    ).json()

    # An approval-gated tool that only exists in this app's registry, to prove an
    # unattended run never offers it to the model.
    original_list_for_run = client.app.state.tool_registry.list_for_run

    async def _with_gated_tool(*, task_id, conversation_id):  # noqa: ANN001
        specs = await original_list_for_run(
            task_id=task_id, conversation_id=conversation_id
        )
        return [
            *specs,
            ToolSpec(
                name="builtin.fake_write",
                model_name="fake_write",
                kind="builtin_data",
                risk_level="write",
                requires_approval=True,
                display_name="需要审批的写操作",
                description="只用于测试",
            ),
        ]

    client.app.state.tool_registry.list_for_run = _with_gated_tool

    # The API only schedules future occurrences; make this one due right now.
    execute_sql(
        database_url,
        "UPDATE schedule SET next_run_at = now() - interval '1 minute' WHERE id = :id",
        id=schedule["id"],
    )

    deadline = time.monotonic() + 30
    current = schedule
    while time.monotonic() < deadline:
        current = client.get(f"/api/v1/schedules/{schedule['id']}").json()
        if current["last_status"] == "dispatched":
            break
        time.sleep(0.2)
    assert current["last_status"] == "dispatched", current

    detail = client.get(f"/api/v1/tasks/{sent['task_id']}").json()
    scheduled = [run for run in detail["runs"] if run["trigger"] == "scheduled"]
    assert len(scheduled) == 1, detail["runs"]
    assert scheduled[0]["schedule_id"] == schedule["id"]

    run = wait_for_run(client, scheduled[0]["id"])
    assert run["status"] == "succeeded"
    assert run["error"] is None

    plan = run_sql(
        database_url,
        "SELECT payload FROM run_event WHERE run_id = :id AND event_type = 'plan'",
        id=run["id"],
    )[0]["payload"]
    assert plan["unattended"] is True
    assert plan["hidden_tools"] == ["fake_write"]
    assert "fake_write" not in plan["tools"]
    assert "load_skill" in plan["tools"]
    assert any("fake_write" in warning for warning in plan["warnings"])

    keys = run_sql(
        database_url,
        "SELECT idempotency_key FROM task_run WHERE id = :id",
        id=run["id"],
    )
    assert keys[0]["idempotency_key"].startswith(f"schedule:{schedule['id']}:")
