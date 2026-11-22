from __future__ import annotations

import asyncio
import time
import uuid

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from reportify.api.app import create_app
from tests.support import (
    event_names,
    make_send_message,
    scripted_model,
    text_step,
    tool_step,
    wait_for_run,
)


def _slow_model(delay: float) -> FunctionModel:
    def function(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="慢速完成。")])

    async def stream_function(messages, info):
        await asyncio.sleep(delay)
        yield "慢速完成。"

    return FunctionModel(function, stream_function=stream_function, model_name="slow")


def test_cancel_stops_the_run(client_factory, database_url) -> None:
    client = client_factory(model=_slow_model(5.0))
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "跑一个很慢的分析")

    time.sleep(0.1)
    cancelled = client.post(f"/api/v1/runs/{sent['run_id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] in {"cancelling", "cancelled"}

    run = wait_for_run(client, sent["run_id"])
    assert run["status"] == "cancelled"

    task = client.get(f"/api/v1/tasks/{sent['task_id']}").json()
    assert task["status"] == "cancelled"
    types = [message["message_type"] for message in
             client.get(f"/api/v1/conversations/{conversation_id}/messages").json()["items"]]
    assert "system_event" in types


def test_cancel_is_idempotent_after_finish(client_factory) -> None:
    client = client_factory([text_step("完成。")])
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "快跑")
    wait_for_run(client, sent["run_id"])

    response = client.post(f"/api/v1/runs/{sent['run_id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"


def test_cancel_unknown_run_is_404(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.post(f"/api/v1/runs/{uuid.uuid4()}/cancel")
    assert response.status_code == 404


def test_loop_detection_aborts_repeated_identical_calls(client_factory) -> None:
    repeated = tool_step("load_skill", {"name": "example"})
    client = client_factory([repeated, repeated, repeated, text_step("不该到这里")])
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "重复调用同一个工具")

    run = wait_for_run(client, sent["run_id"])
    assert run["status"] == "failed"
    assert run["error"]["code"] == "loop_detected"
    assert "error" in event_names(client, sent["run_id"])


def test_budget_exhaustion_marks_run_failed(settings) -> None:
    budget_settings = settings.model_copy(update={"run_request_limit": 1})
    model = scripted_model(
        [
            tool_step("load_skill", {"name": "example"}),
            text_step("第二轮请求会超预算"),
        ]
    )
    app = create_app(budget_settings, model=model)
    with TestClient(app) as client:
        conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
        sent = make_send_message(client, conversation_id, "触发预算上限")
        run = wait_for_run(client, sent["run_id"])

    assert run["status"] == "failed"
    assert run["error"]["code"] == "budget_exceeded"


def test_model_not_configured_returns_503(client) -> None:
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "没有配置模型"},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "model_not_configured"


def test_second_run_in_busy_conversation_returns_409(client_factory) -> None:
    client = client_factory(model=_slow_model(3.0))
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    first = make_send_message(client, conversation_id, "第一个问题")
    time.sleep(0.1)

    second = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "并发第二个问题"},
    )
    assert second.status_code == 409
    assert second.json()["code"] == "conversation_busy"

    client.post(f"/api/v1/runs/{first['run_id']}/cancel")
    wait_for_run(client, first["run_id"])
