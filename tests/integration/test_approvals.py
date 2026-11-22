from __future__ import annotations

import json
import time

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from tests.integration.mcp_helpers import (
    create_server,
    discover,
    expected_model_name,
    grant,
    unique_slug,
)
from tests.support import (
    make_send_message,
    run_sql,
    text_step,
    tool_step,
    wait_for_run,
)

WAITING = "waiting_approval"


def _wait_for_status(client, run_id: str, status: str, *, timeout: float = 25.0) -> dict:
    deadline = time.monotonic() + timeout
    body: dict = {}
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/runs/{run_id}").json()
        if body["status"] == status:
            return body
        time.sleep(0.05)
    raise AssertionError(
        f"run {run_id} never reached {status}; last={body.get('status')} "
        f"error={body.get('error')}"
    )


def _parked_run(
    client,
    fake_mcp,
    slug: str,
    *,
    tool: str = "echo",
) -> tuple[dict, str]:
    """Create a server for ``slug``, grant ``tool`` as destructive, park a run."""
    server = create_server(client, fake_mcp.url, slug)
    discover(client, server["id"])
    grant(client, server["id"], tool, risk="destructive", ack=True)

    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "è°ƒç”¨å±é™©å·¥å…·")
    _wait_for_status(client, sent["run_id"], WAITING)
    return sent, expected_model_name(slug, tool)


def _pending(client, run_id: str) -> list[dict]:
    return client.get(f"/api/v1/runs/{run_id}/approvals").json()["approvals"]


def test_destructive_tool_waits_for_approval(client_factory, fake_mcp, database_url) -> None:
    slug = unique_slug()
    model_name = expected_model_name(slug, "echo")
    client = client_factory([tool_step(model_name, {"text": "hi"}), text_step("å·²å¤„ç†ã€‚")])
    sent, _model_name = _parked_run(client, fake_mcp, slug)

    run = client.get(f"/api/v1/runs/{sent['run_id']}").json()
    assert run["status"] == WAITING
    assert fake_mcp.calls == []  # approval gates execution

    # Read events from the database: the SSE endpoint stays open on a parked run.
    events = run_sql(
        database_url,
        "SELECT event_type FROM run_event WHERE run_id = :run_id ORDER BY sequence",
        run_id=sent["run_id"],
    )
    assert "approval_required" in [row["event_type"] for row in events]

    pending = _pending(client, sent["run_id"])
    assert len(pending) == 1
    assert pending[0]["tool_name"] == model_name
    assert pending[0]["risk"] == "destructive"
    assert pending[0]["decision"] == "pending"

    task = client.get(f"/api/v1/tasks/{sent['task_id']}").json()
    assert task["status"] == WAITING

    audits = run_sql(
        database_url,
        "SELECT status FROM tool_call_audit WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert audits == []


def test_approving_resumes_the_same_run(client_factory, fake_mcp) -> None:
    slug = unique_slug()
    model_name = expected_model_name(slug, "echo")
    client = client_factory([tool_step(model_name, {"text": "hi"}), text_step("å·²å¤„ç†ã€‚")])
    sent, _model_name = _parked_run(client, fake_mcp, slug)

    approval_id = _pending(client, sent["run_id"])[0]["approval_id"]
    response = client.post(
        f"/api/v1/runs/{sent['run_id']}/approvals/{approval_id}",
        json={"decision": "approve"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "resuming"

    final = wait_for_run(client, sent["run_id"], timeout=40)
    assert final["status"] == "succeeded", final
    assert fake_mcp.calls == ["echo:hi"]

    task = client.get(f"/api/v1/tasks/{sent['task_id']}").json()
    assert task["status"] == "completed"
    assert len(task["runs"]) == 1  # resumed in place
    assert _pending(client, sent["run_id"]) == []


def test_denying_skips_the_tool(client_factory, fake_mcp, database_url) -> None:
    slug = unique_slug()
    model_name = expected_model_name(slug, "echo")
    client = client_factory([tool_step(model_name, {"text": "hi"}), text_step("å·²å–æ¶ˆã€‚")])
    sent, _model_name = _parked_run(client, fake_mcp, slug)

    approval_id = _pending(client, sent["run_id"])[0]["approval_id"]
    response = client.post(
        f"/api/v1/runs/{sent['run_id']}/approvals/{approval_id}",
        json={"decision": "deny"},
    )
    assert response.status_code == 200

    final = wait_for_run(client, sent["run_id"], timeout=40)
    assert final["status"] == "succeeded", final
    assert fake_mcp.calls == []

    audits = run_sql(
        database_url,
        "SELECT status, error_code FROM tool_call_audit WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert audits
    assert audits[0]["status"] == "rejected"
    assert audits[0]["error_code"] == "approval_rejected"


def test_partial_decision_keeps_waiting(client_factory, fake_mcp) -> None:
    slug = unique_slug()
    first = expected_model_name(slug, "echo")
    second = expected_model_name(slug, "slow")

    def _returns(messages) -> int:
        return sum(
            1
            for message in messages
            for part in getattr(message, "parts", ())
            if type(part).__name__ in {"ToolReturnPart", "RetryPromptPart"}
        )

    def model_fn(messages, info):
        if _returns(messages) == 0:
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name=first, args={"text": "a"}, tool_call_id="c1"),
                    ToolCallPart(tool_name=second, args={"seconds": 0}, tool_call_id="c2"),
                ]
            )
        return ModelResponse(parts=[TextPart(content="éƒ½å¤„ç†å®Œäº†ã€‚")])

    async def stream_fn(messages, info):
        if _returns(messages) == 0:
            yield {
                0: DeltaToolCall(
                    name=first, json_args=json.dumps({"text": "a"}), tool_call_id="c1"
                )
            }
            yield {
                1: DeltaToolCall(
                    name=second, json_args=json.dumps({"seconds": 0}), tool_call_id="c2"
                )
            }
            return
        yield "éƒ½å¤„ç†å®Œäº†ã€‚"

    client = client_factory(model=FunctionModel(model_fn, stream_function=stream_fn))
    server = create_server(client, fake_mcp.url, slug)
    discover(client, server["id"])
    grant(client, server["id"], "echo", risk="destructive", ack=True)
    grant(client, server["id"], "slow", risk="destructive", ack=True)

    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "ä¸¤ä¸ªå±é™©è°ƒç”¨")
    _wait_for_status(client, sent["run_id"], WAITING)

    approvals = _pending(client, sent["run_id"])
    assert len(approvals) == 2

    first_decision = client.post(
        f"/api/v1/runs/{sent['run_id']}/approvals/{approvals[0]['approval_id']}",
        json={"decision": "approve"},
    ).json()
    assert first_decision["status"] == WAITING
    assert client.get(f"/api/v1/runs/{sent['run_id']}").json()["status"] == WAITING

    client.post(
        f"/api/v1/runs/{sent['run_id']}/approvals/{approvals[1]['approval_id']}",
        json={"decision": "approve"},
    )
    final = wait_for_run(client, sent["run_id"], timeout=40)
    assert final["status"] == "succeeded", final


def test_unknown_approval_is_404(client_factory, fake_mcp) -> None:
    slug = unique_slug()
    model_name = expected_model_name(slug, "echo")
    client = client_factory([tool_step(model_name, {"text": "x"}), text_step("ok")])
    sent, _model_name = _parked_run(client, fake_mcp, slug)

    response = client.post(
        f"/api/v1/runs/{sent['run_id']}/approvals/not-a-real-id",
        json={"decision": "approve"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_approval_on_finished_run_is_409(client_factory) -> None:
    client = client_factory([text_step("å®Œæˆã€‚")])
    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "æ™®é€šè¯·æ±‚")
    wait_for_run(client, sent["run_id"])

    response = client.post(
        f"/api/v1/runs/{sent['run_id']}/approvals/whatever",
        json={"decision": "approve"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


def test_waiting_run_blocks_new_messages(client_factory, fake_mcp) -> None:
    slug = unique_slug()
    model_name = expected_model_name(slug, "echo")
    client = client_factory([tool_step(model_name, {"text": "x"}), text_step("ok")])
    sent, _model_name = _parked_run(client, fake_mcp, slug)

    conversation_id = client.get(f"/api/v1/tasks/{sent['task_id']}").json()[
        "conversation_id"
    ]
    second = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "å†æ¥ä¸€ä¸ª"},
    )
    assert second.status_code == 409
    assert second.json()["code"] == "conversation_busy"

