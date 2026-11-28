from __future__ import annotations

import uuid

from tests.support import make_send_message, run_sql, text_step, wait_for_run


def test_memory_crud_and_search(client_factory, database_url) -> None:
    client = client_factory([])

    created = client.post(
        "/api/v1/memory",
        json={
            "content": "分析默认使用最近 30 天的时间范围",
            "kind": "preference",
            "tags": ["口径"],
        },
    )
    assert created.status_code == 201, created.text
    memory = created.json()
    assert memory["scope"] == "global"
    assert memory["kind"] == "preference"

    listed = client.get("/api/v1/memory").json()
    assert [item["id"] for item in listed] == [memory["id"]]

    found = client.get("/api/v1/memory/search", params={"q": "最近 30 天销售"}).json()
    assert [item["id"] for item in found] == [memory["id"]]

    unrelated = client.get("/api/v1/memory/search", params={"q": "配色方案"}).json()
    assert unrelated == []

    deleted = client.delete(f"/api/v1/memory/{memory['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/memory").json() == []

    missing = client.delete(f"/api/v1/memory/{uuid.uuid4()}")
    assert missing.status_code == 404


def test_conversation_scoped_memory_is_isolated(client_factory, database_url) -> None:
    client = client_factory([])
    conversation = client.post("/api/v1/conversations", json={}).json()
    other = client.post("/api/v1/conversations", json={}).json()

    scoped = client.post(
        "/api/v1/memory",
        json={
            "content": "这个会话只关注华东区",
            "scope": "conversation",
            "conversation_id": conversation["id"],
        },
    )
    assert scoped.status_code == 201, scoped.text

    inside = client.get(
        "/api/v1/memory/search",
        params={"q": "华东区销售", "conversation_id": conversation["id"]},
    ).json()
    assert [item["id"] for item in inside] == [scoped.json()["id"]]

    outside = client.get(
        "/api/v1/memory/search",
        params={"q": "华东区销售", "conversation_id": other["id"]},
    ).json()
    assert outside == []

    unknown = client.post(
        "/api/v1/memory",
        json={
            "content": "x",
            "scope": "conversation",
            "conversation_id": str(uuid.uuid4()),
        },
    )
    assert unknown.status_code == 404


def test_invalid_scope_is_rejected(client_factory, database_url) -> None:
    client = client_factory([])
    response = client.post("/api/v1/memory", json={"content": "x", "scope": "team"})
    assert response.status_code == 422


def test_memory_is_injected_into_the_plan(client_factory, database_url) -> None:
    client = client_factory([text_step("好的。")])
    memory = client.post(
        "/api/v1/memory",
        json={"content": "分析默认使用最近 30 天的时间范围"},
    ).json()

    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "分析最近 30 天的销售数据")
    assert wait_for_run(client, sent["run_id"])["status"] == "succeeded"

    plan = run_sql(
        database_url,
        "SELECT payload FROM run_event WHERE run_id = :id AND event_type = 'plan'",
        id=sent["run_id"],
    )[0]["payload"]
    assert plan["memory_used"] == [memory["id"]]

    used = client.get("/api/v1/memory").json()[0]
    assert used["last_used_at"] is not None
