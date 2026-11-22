from __future__ import annotations

import json

from tests.integration.mcp_helpers import expected_model_name, unique_slug
from tests.support import (
    event_names,
    make_send_message,
    run_sql,
    text_step,
    tool_step,
    wait_for_run,
)


def _create_server(client, url: str, slug: str, **extra) -> dict:
    response = client.post(
        "/api/v1/mcp/servers",
        json={"name": f"MCP {slug}", "slug": slug, "url": url, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _discover(client, server_id: str) -> dict:
    response = client.post(f"/api/v1/mcp/servers/{server_id}/discover")
    assert response.status_code == 200, response.text
    return response.json()


def _grant(client, server_id: str, tool_name: str, *, risk: str = "read") -> dict:
    tools = client.get(f"/api/v1/mcp/servers/{server_id}/tools").json()
    tool = next(item for item in tools if item["name"].endswith(f".{tool_name}"))
    response = client.put(
        f"/api/v1/mcp/tools/{tool['id']}/grant",
        json={"allowed": True, "risk_level": risk, "risk_acknowledged": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_server_lifecycle_api(client_factory, fake_mcp) -> None:
    client = client_factory([text_step("ok")])
    slug = unique_slug()
    created = _create_server(client, fake_mcp.url, slug)
    assert created["status"] == "unknown"
    assert created["has_secret"] is False

    tested = client.post(f"/api/v1/mcp/servers/{created['id']}/test")
    assert tested.status_code == 200
    assert tested.json()["ok"] is True
    assert tested.json()["tool_count"] == 3

    discovered = _discover(client, created["id"])
    assert discovered["tools_added"] == 3

    tools = client.get(f"/api/v1/mcp/servers/{created['id']}/tools").json()
    assert {tool["name"] for tool in tools} == {
        f"mcp.{slug}.echo",
        f"mcp.{slug}.slow",
        f"mcp.{slug}.boom",
    }
    assert all(tool["granted"] is False for tool in tools)

    listed = client.get("/api/v1/mcp/servers").json()
    assert any(item["id"] == created["id"] for item in listed)


def test_bearer_token_is_never_echoed(client_factory, fake_mcp) -> None:
    client = client_factory([text_step("ok")])
    created = _create_server(
        client,
        fake_mcp.url,
        unique_slug(),
        auth_type="bearer",
        token="super-secret-token",
    )
    assert created["has_secret"] is True
    assert "super-secret-token" not in json.dumps(created)


def test_ssrf_is_rejected_at_config_time(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.post(
        "/api/v1/mcp/servers",
        json={
            "name": "metadata",
            "slug": "metadata-probe",
            "url": "http://169.254.169.254/latest/meta-data/",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


def test_grant_requires_risk_acknowledgement(client_factory, fake_mcp) -> None:
    client = client_factory([text_step("ok")])
    slug = unique_slug()
    created = _create_server(client, fake_mcp.url, slug)
    _discover(client, created["id"])
    tools = client.get(f"/api/v1/mcp/servers/{created['id']}/tools").json()
    tool = next(item for item in tools if item["name"].endswith(".echo"))

    refused = client.put(
        f"/api/v1/mcp/tools/{tool['id']}/grant",
        json={"allowed": True},
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "validation_failed"

    granted = client.put(
        f"/api/v1/mcp/tools/{tool['id']}/grant",
        json={"allowed": True, "risk_level": "read", "risk_acknowledged": True},
    )
    assert granted.status_code == 200
    assert granted.json()["granted"] is True


def test_authorized_mcp_tool_is_callable_by_agent(
    client_factory,
    fake_mcp,
    database_url,
) -> None:
    slug = unique_slug()
    model_name = expected_model_name(slug, "echo")
    client = client_factory(
        [
            tool_step(model_name, {"text": "hello"}),
            text_step("MCP 工具返回完成。"),
        ]
    )
    created = _create_server(client, fake_mcp.url, slug)
    _discover(client, created["id"])
    granted = _grant(client, created["id"], "echo")
    assert granted["granted"] is True

    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "调用 MCP echo")
    run = wait_for_run(client, sent["run_id"], timeout=30)

    assert run["status"] == "succeeded", run
    assert "tool_call" in event_names(client, sent["run_id"])

    audits = run_sql(
        database_url,
        "SELECT tool_name, source, status FROM tool_call_audit WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert len(audits) == 1
    assert audits[0]["tool_name"] == model_name
    assert audits[0]["source"] == "mcp"
    assert audits[0]["status"] == "succeeded"

    api_audits = client.get("/api/v1/mcp/audits", params={"tool_name": model_name}).json()
    assert any(item["run_id"] == sent["run_id"] for item in api_audits)


def test_ungranted_mcp_tool_is_invisible(
    client_factory,
    fake_mcp,
    database_url,
) -> None:
    slug = unique_slug()
    model_name = expected_model_name(slug, "echo")
    client = client_factory(
        [
            tool_step(model_name, {"text": "hello"}),
            text_step("不该到这里。"),
        ]
    )
    created = _create_server(client, fake_mcp.url, slug)
    _discover(client, created["id"])  # discovered but not granted

    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "调用未授权的 MCP 工具")
    run = wait_for_run(client, sent["run_id"], timeout=30)

    # The SDK hands an unavailable tool back to the model; nothing executed.
    assert run["status"] == "succeeded"
    audits = run_sql(
        database_url,
        "SELECT status, error_code FROM tool_call_audit WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert len(audits) == 1
    assert audits[0]["status"] == "denied"
    assert audits[0]["error_code"] == "unknown_tool"


def test_mcp_timeout_is_audited_as_timeout(
    client_factory,
    fake_mcp,
    database_url,
) -> None:
    slug = unique_slug()
    model_name = expected_model_name(slug, "slow")
    client = client_factory(
        [
            tool_step(model_name, {"seconds": 3}),
            text_step("超时后继续。"),
        ]
    )
    created = _create_server(
        client,
        fake_mcp.url,
        slug,
        options={"read_timeout_seconds": 1},
    )
    _discover(client, created["id"])
    _grant(client, created["id"], "slow")

    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "调用慢工具")
    run = wait_for_run(client, sent["run_id"], timeout=40)
    assert run["status"] == "succeeded", run

    audits = run_sql(
        database_url,
        "SELECT status, error_code FROM tool_call_audit WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert audits[0]["status"] == "timeout"
    assert audits[0]["error_code"] == "timeout"


def test_unreachable_server_is_reported_in_plan(
    client_factory,
    fake_mcp,
    database_url,
) -> None:
    slug = unique_slug()
    client = client_factory([text_step("没有 MCP 也能继续。")])
    created = _create_server(client, fake_mcp.url, slug)
    _discover(client, created["id"])
    _grant(client, created["id"], "echo")
    fake_mcp.stop()

    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "MCP 不可达时继续")
    run = wait_for_run(client, sent["run_id"], timeout=30)

    assert run["status"] == "succeeded", run
    plans = run_sql(
        database_url,
        "SELECT payload FROM run_event WHERE run_id = :run_id AND event_type = 'plan'",
        run_id=sent["run_id"],
    )
    payload = plans[0]["payload"]
    assert slug in payload["mcp_unavailable"]
    assert any("unreachable" in warning for warning in payload["warnings"])


def test_disabled_server_tools_are_gone_from_runs(
    client_factory,
    fake_mcp,
    database_url,
) -> None:
    slug = unique_slug()
    model_name = expected_model_name(slug, "echo")
    client = client_factory(
        [
            tool_step(model_name, {"text": "x"}),
            text_step("不该到这里。"),
        ]
    )
    created = _create_server(client, fake_mcp.url, slug)
    _discover(client, created["id"])
    _grant(client, created["id"], "echo")
    deleted = client.delete(f"/api/v1/mcp/servers/{created['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["enabled"] is False

    conversation_id = client.post("/api/v1/conversations", json={}).json()["id"]
    sent = make_send_message(client, conversation_id, "禁用后不该能调用")
    run = wait_for_run(client, sent["run_id"], timeout=30)
    assert run["status"] == "succeeded"
    audits = run_sql(
        database_url,
        "SELECT status, error_code FROM tool_call_audit WHERE run_id = :run_id",
        run_id=sent["run_id"],
    )
    assert len(audits) == 1
    assert audits[0]["status"] == "denied"
    assert audits[0]["error_code"] == "unknown_tool"


def test_unknown_server_returns_404(client_factory) -> None:
    import uuid

    client = client_factory([text_step("ok")])
    response = client.get(f"/api/v1/mcp/servers/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
