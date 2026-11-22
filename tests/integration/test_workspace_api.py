from __future__ import annotations

from tests.support import text_step


def test_list_workspace_files(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get("/api/v1/workspace/files")
    assert response.status_code == 200
    payload = response.json()
    paths = {item["path"] for item in payload["files"]}
    assert "AGENTS.md" in paths
    assert "skills/example/SKILL.md" in paths
    assert "report-templates/default.yaml" in paths
    assert payload["count"] == len(payload["files"])
    for item in payload["files"]:
        assert len(item["hash"]) == 64
        assert item["size"] > 0


def test_read_workspace_file(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get("/api/v1/workspace/files/AGENTS.md")
    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == "AGENTS.md"
    assert "Python" in payload["content"]


def test_hidden_files_are_not_listed(client_factory, settings) -> None:
    hidden = settings.workspace_dir / ".secret-note"
    hidden.write_text("nope", encoding="utf-8")
    try:
        client = client_factory([text_step("ok")])
        paths = {item["path"] for item in client.get("/api/v1/workspace/files").json()["files"]}
        assert ".secret-note" not in paths
    finally:
        hidden.unlink(missing_ok=True)


def test_path_traversal_is_rejected(client_factory, settings) -> None:
    outside = settings.workspace_dir.parent / "outside.txt"
    outside.write_text("should not be readable", encoding="utf-8")
    try:
        client = client_factory([text_step("ok")])
        for path in ["../outside.txt", "..%2Foutside.txt", "skills/../../outside.txt"]:
            response = client.get(f"/api/v1/workspace/files/{path}")
            assert response.status_code in {400, 404, 422}, (path, response.status_code)
            assert "should not be readable" not in response.text
    finally:
        outside.unlink(missing_ok=True)


def test_unknown_file_is_404(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get("/api/v1/workspace/files/does-not-exist.md")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_reload_writes_audits_and_is_idempotent(client_factory) -> None:
    client = client_factory([text_step("ok")])

    first = client.post("/api/v1/workspace/reload").json()
    assert first["files"] > 0
    assert first["audit"]["loaded"] > 0

    second = client.post("/api/v1/workspace/reload").json()
    assert second["audit"]["loaded"] == 0
    assert second["audit"]["changed"] == 0


def test_changed_file_is_recorded(client_factory, settings) -> None:
    skill_path = settings.workspace_dir / "skills" / "example" / "SKILL.md"
    original = skill_path.read_text(encoding="utf-8")
    client = client_factory([text_step("ok")])
    client.post("/api/v1/workspace/reload")

    try:
        skill_path.write_text(original + "\n<!-- changed -->\n", encoding="utf-8")
        result = client.post("/api/v1/workspace/reload").json()
        assert result["audit"]["changed"] >= 1
    finally:
        skill_path.write_text(original, encoding="utf-8")


def test_audits_are_listed_and_filtered(client_factory) -> None:
    client = client_factory([text_step("ok")])
    client.post("/api/v1/workspace/reload")

    response = client.get("/api/v1/workspace/audits?limit=50")
    assert response.status_code == 200
    rows = response.json()
    assert rows
    assert {"id", "file_path", "content_hash", "action", "actor"} <= set(rows[0])

    changed = client.get("/api/v1/workspace/audits?action=changed").json()
    assert all(row["action"] == "changed" for row in changed)


def test_config_endpoint_hides_secrets(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get("/api/v1/config")
    assert response.status_code == 200
    payload = response.json()

    assert payload["version"]
    assert payload["features"]["approvals"] is True
    assert payload["features"]["scheduler"] is False
    assert "limits" in payload and payload["limits"]["run_request_limit"] > 0

    body = response.text
    for secret in ("test-secret", "secret_key", "auth_token", "api_key"):
        assert secret not in body, secret
