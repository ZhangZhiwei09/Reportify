from __future__ import annotations

from tests.support import text_step


def test_list_skills(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get("/api/v1/skills")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert "example" in names


def test_skill_detail_includes_body(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get("/api/v1/skills/example")
    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "示例分析"
    assert "name: example" in payload["content"]
    assert payload["applies_to"] == ["示例", "测试"]


def test_validate_skill(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.post("/api/v1/skills/example/validate")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_unknown_skill_is_404(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get("/api/v1/skills/does-not-exist")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_invalid_skill_name_is_rejected(client_factory) -> None:
    client = client_factory([text_step("ok")])
    for name in ["Bad Name", "UPPER", "a/b", "x.md"]:
        response = client.get(f"/api/v1/skills/{name}")
        assert response.status_code in {400, 404, 422}, (name, response.status_code)

    response = client.get("/api/v1/skills/a%2F..%2F..%2FAGENTS.md")
    assert response.status_code in {400, 404, 422}
    assert "SKILL" not in response.text


def test_reload_returns_count(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.post("/api/v1/skills/reload")
    assert response.status_code == 200
    assert response.json()["skills"] >= 1


def test_skill_change_is_visible_without_restart(client_factory, settings) -> None:
    """Files are the source of truth: a new skill appears on the next call."""
    skill_dir = settings.workspace_dir / "skills" / "tmp-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: tmp-skill\n"
        "display_name: 临时技能\n"
        "description: 用于验证热加载\n"
        "version: 1\n"
        "---\n\n"
        "## 步骤\n\n1. 做点事\n",
        encoding="utf-8",
    )
    try:
        client = client_factory([text_step("ok")])
        names = {item["name"] for item in client.get("/api/v1/skills").json()}
        assert "tmp-skill" in names
    finally:
        (skill_dir / "SKILL.md").unlink(missing_ok=True)
        skill_dir.rmdir()
