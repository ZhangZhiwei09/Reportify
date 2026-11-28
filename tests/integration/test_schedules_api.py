from __future__ import annotations

import uuid
from datetime import UTC, datetime

from reportify.core.errors import ConversationBusy
from tests.support import make_send_message, run_sql, wait_for_run


def _new_task(client) -> tuple[str, str]:
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "每天的销售分析")
    wait_for_run(client, sent["run_id"])
    return conversation_id, sent["task_id"]


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_schedule_crud(client_factory, database_url) -> None:
    client = client_factory([])
    conversation_id, task_id = _new_task(client)

    created = client.post(
        "/api/v1/schedules",
        json={"task_id": task_id, "cron": "0 9 * * *", "timezone": "Asia/Shanghai"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["task_id"] == task_id
    assert body["conversation_id"] == conversation_id
    assert body["enabled"] is True
    assert body["run_count"] == 0
    assert body["name"] == "每天的销售分析"
    assert _iso(body["next_run_at"]).tzinfo is not None
    assert _iso(body["next_run_at"]) > datetime.now(UTC)
    schedule_id = body["id"]

    listed = client.get("/api/v1/schedules").json()
    assert schedule_id in [item["id"] for item in listed]

    paused = client.patch(f"/api/v1/schedules/{schedule_id}", json={"enabled": False})
    assert paused.status_code == 200
    assert paused.json()["enabled"] is False

    renamed = client.patch(f"/api/v1/schedules/{schedule_id}", json={"name": "早报"})
    assert renamed.json()["name"] == "早报"

    moved = client.patch(
        f"/api/v1/schedules/{schedule_id}",
        json={"cron": "30 8 * * 1-5", "timezone": "UTC"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["cron"] == "30 8 * * 1-5"
    assert moved.json()["timezone"] == "UTC"

    deleted = client.delete(f"/api/v1/schedules/{schedule_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/schedules/{schedule_id}").status_code == 404


def test_schedule_validation_errors(client_factory, database_url) -> None:
    client = client_factory([])
    _, task_id = _new_task(client)

    bad_cron = client.post(
        "/api/v1/schedules",
        json={"task_id": task_id, "cron": "*/0 * * * *"},
    )
    assert bad_cron.status_code == 400
    assert bad_cron.json()["code"] == "invalid_argument"

    never_fires = client.post(
        "/api/v1/schedules",
        json={"task_id": task_id, "cron": "0 0 30 2 *"},
    )
    assert never_fires.status_code == 400

    bad_tz = client.post(
        "/api/v1/schedules",
        json={"task_id": task_id, "cron": "0 9 * * *", "timezone": "Mars/Base"},
    )
    assert bad_tz.status_code == 400

    unknown_task = client.post(
        "/api/v1/schedules",
        json={"task_id": str(uuid.uuid4()), "cron": "0 9 * * *"},
    )
    assert unknown_task.status_code == 404


def test_duplicate_schedule_is_a_conflict(client_factory, database_url) -> None:
    client = client_factory([])
    _, task_id = _new_task(client)
    payload = {"task_id": task_id, "cron": "0 9 * * *", "timezone": "UTC"}
    assert client.post("/api/v1/schedules", json=payload).status_code == 201

    duplicate = client.post("/api/v1/schedules", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "conflict"


def test_run_now_dispatches_a_run(client_factory, database_url) -> None:
    client = client_factory([])
    _, task_id = _new_task(client)
    schedule_id = client.post(
        "/api/v1/schedules",
        json={"task_id": task_id, "cron": "0 9 * * *"},
    ).json()["id"]

    response = client.post(f"/api/v1/schedules/{schedule_id}/run")
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    run = wait_for_run(client, run_id)
    assert run["status"] == "succeeded"
    assert run["trigger"] == "api"
    assert run["schedule_id"] == schedule_id

    schedule = client.get(f"/api/v1/schedules/{schedule_id}").json()
    assert schedule["last_status"] == "dispatched"
    assert schedule["last_run_id"] == run_id
    assert schedule["run_count"] == 1
    assert schedule["last_run_at"] is not None

    runs = client.get(f"/api/v1/schedules/{schedule_id}/runs").json()
    assert [item["id"] for item in runs] == [run_id]

    stored = run_sql(
        database_url,
        "SELECT trigger, schedule_id, idempotency_key FROM task_run WHERE id = :id",
        id=run_id,
    )
    assert stored[0]["trigger"] == "api"
    assert str(stored[0]["schedule_id"]) == schedule_id
    assert stored[0]["idempotency_key"].startswith(f"schedule:{schedule_id}:manual:")


def test_run_now_records_a_busy_conversation(client_factory, database_url) -> None:
    client = client_factory([])
    _, task_id = _new_task(client)
    schedule_id = client.post(
        "/api/v1/schedules",
        json={"task_id": task_id, "cron": "0 9 * * *"},
    ).json()["id"]

    async def _busy(request):  # noqa: ANN001 - signature only needs to accept one arg
        raise ConversationBusy()

    client.app.state.runtime.start = _busy

    response = client.post(f"/api/v1/schedules/{schedule_id}/run")
    assert response.status_code == 409
    assert response.json()["code"] == "conversation_busy"

    schedule = client.get(f"/api/v1/schedules/{schedule_id}").json()
    assert schedule["last_status"] == "skipped"
    assert schedule["last_error"]["code"] == "conversation_busy"
    assert schedule["last_run_id"] is None


def test_idempotency_key_returns_the_same_run(client_factory, database_url) -> None:
    client = client_factory([])
    _, task_id = _new_task(client)

    headers = {"Idempotency-Key": "fixed-key-for-retry"}
    first = client.post(f"/api/v1/tasks/{task_id}/runs", headers=headers)
    assert first.status_code == 201, first.text
    assert wait_for_run(client, first.json()["id"])["status"] == "succeeded"

    second = client.post(f"/api/v1/tasks/{task_id}/runs", headers=headers)
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]

    rows = run_sql(
        database_url,
        "SELECT count(*) AS total FROM task_run WHERE idempotency_key = :key",
        key="fixed-key-for-retry",
    )
    assert rows[0]["total"] == 1
