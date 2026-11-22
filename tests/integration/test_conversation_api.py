from __future__ import annotations

import uuid

from tests.support import make_send_message, text_step, wait_for_run


def test_create_and_list_conversations(client_factory) -> None:
    client = client_factory([text_step("ok")])

    created = client.post("/api/v1/conversations", json={"title": "销售分析"})
    assert created.status_code == 201
    body = created.json()
    assert body["title"] == "销售分析"
    assert body["status"] == "active"

    listed = client.get("/api/v1/conversations")
    assert listed.status_code == 200
    assert any(item["id"] == body["id"] for item in listed.json())


def test_default_title_when_omitted(client_factory) -> None:
    client = client_factory([text_step("ok")])
    body = client.post("/api/v1/conversations", json={}).json()
    assert body["title"] == "新会话"


def test_get_and_patch_conversation(client_factory) -> None:
    client = client_factory([text_step("ok")])
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]

    patched = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"title": "改名", "status": "archived"},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "改名"
    assert patched.json()["status"] == "archived"


def test_unknown_conversation_returns_404(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get(f"/api/v1/conversations/{uuid.uuid4()}")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert body["instance"].startswith("/api/v1/conversations/")


def test_archived_conversation_rejects_messages(client_factory) -> None:
    client = client_factory([text_step("ok")])
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    client.patch(f"/api/v1/conversations/{conversation_id}", json={"status": "archived"})

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "你好"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_argument"


def test_send_message_runs_and_records_messages(client_factory) -> None:
    client = client_factory([text_step("这是结论。")])
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]

    sent = make_send_message(client, conversation_id, "分析一下")
    assert set(sent) == {"message_id", "task_id", "run_id"}

    run = wait_for_run(client, sent["run_id"])
    assert run["status"] == "succeeded"

    page = client.get(f"/api/v1/conversations/{conversation_id}/messages").json()
    roles = [(item["role"], item["message_type"]) for item in page["items"]]
    assert ("user", "user_message") in roles
    assert ("assistant", "assistant_message") in roles
    sequences = [item["sequence"] for item in page["items"]]
    assert sequences == sorted(sequences)
    assert page["items"][0]["content"] == "分析一下"


def test_message_pagination_with_after_sequence(client_factory) -> None:
    client = client_factory([text_step("一"), text_step("二")])
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]

    for content in ("第一个问题", "第二个问题"):
        sent = make_send_message(client, conversation_id, content)
        wait_for_run(client, sent["run_id"])

    full = client.get(f"/api/v1/conversations/{conversation_id}/messages").json()
    assert len(full["items"]) >= 4
    cursor = full["items"][1]["sequence"]

    rest = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        params={"after_sequence": cursor, "limit": 2},
    ).json()
    assert rest["items"]
    assert all(item["sequence"] > cursor for item in rest["items"])
    assert rest["has_more"] is True
    assert rest["next_after_sequence"] == rest["items"][-1]["sequence"]


def test_second_message_in_same_task_creates_new_run(client_factory) -> None:
    client = client_factory([text_step("一"), text_step("二")])
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]

    first = make_send_message(client, conversation_id, "第一个目标")
    wait_for_run(client, first["run_id"])
    second = make_send_message(
        client,
        conversation_id,
        "补充要求",
        task_id=first["task_id"],
    )
    wait_for_run(client, second["run_id"])

    assert second["task_id"] == first["task_id"]
    detail = client.get(f"/api/v1/tasks/{first['task_id']}").json()
    assert len(detail["runs"]) == 2
    assert detail["status"] == "completed"


def test_task_listing_and_detail(client_factory) -> None:
    client = client_factory([text_step("ok")])
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "目标 A")
    wait_for_run(client, sent["run_id"])

    tasks = client.get(f"/api/v1/conversations/{conversation_id}/tasks").json()
    assert any(task["id"] == sent["task_id"] for task in tasks)

    detail = client.get(f"/api/v1/tasks/{sent['task_id']}").json()
    assert detail["goal"] == "目标 A"
    assert detail["runs"][0]["id"] == sent["run_id"]
    assert detail["plan"] is not None


def test_empty_content_is_rejected(client_factory) -> None:
    client = client_factory([text_step("ok")])
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "   "},
    )
    assert response.status_code == 400
