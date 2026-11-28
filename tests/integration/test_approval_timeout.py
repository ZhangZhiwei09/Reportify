from __future__ import annotations

import time

from tests.integration.mcp_helpers import (
    create_server,
    discover,
    expected_model_name,
    grant,
    unique_slug,
)
from tests.support import make_send_message, run_sql, text_step, tool_step


def _wait_for_status(client, run_id: str, status: str, *, timeout: float = 25.0) -> dict:
    deadline = time.monotonic() + timeout
    body: dict = {}
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/runs/{run_id}").json()
        if body["status"] == status:
            return body
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} never reached {status}; last={body.get('status')}")


def test_parked_approval_expires_and_is_denied(
    client_factory,
    fake_mcp,
    settings,
    database_url,
) -> None:
    slug = unique_slug()
    model_name = expected_model_name(slug, "echo")
    fast = settings.model_copy(update={"approval_timeout_seconds": 1})
    client = client_factory(
        [tool_step(model_name, {"text": "hi"}), text_step("已处理。")],
        settings_override=fast,
    )

    server = create_server(client, fake_mcp.url, slug)
    discover(client, server["id"])
    grant(client, server["id"], "echo", risk="destructive", ack=True)

    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "调用危险工具")

    # Parked first, then expired by the timer without any human decision.
    _wait_for_status(client, sent["run_id"], "waiting_approval")
    run = _wait_for_status(client, sent["run_id"], "succeeded", timeout=20)

    assert run["error"] is None
    assert fake_mcp.calls == []  # a denied tool never executes

    # The denial is audited like a manual reject.
    audits = run_sql(
        database_url,
        "SELECT tool_name, status, error_code FROM tool_call_audit "
        "WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert [(row["status"], row["error_code"]) for row in audits] == [
        ("rejected", "approval_rejected")
    ]

    messages = client.get(
        f"/api/v1/conversations/{conversation_id}/messages"
    ).json()["items"]
    assert any("审批超时" in item["content"] for item in messages)
