from __future__ import annotations

from tests.support import text_step


def test_list_templates(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get("/api/v1/report-templates")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert "default" in names


def test_template_detail_returns_raw_yaml(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get("/api/v1/report-templates/default")
    assert response.status_code == 200
    payload = response.json()
    assert payload["sections"] == ["概览", "趋势"]
    assert "sections:" in payload["raw"]


def test_validate_template_returns_sections(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.post("/api/v1/report-templates/default/validate")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["sections"] == ["概览", "趋势"]


def test_unknown_template_is_404(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get("/api/v1/report-templates/nope")
    assert response.status_code == 404


def test_invalid_template_name_is_rejected(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.get("/api/v1/report-templates/Bad%20Name")
    assert response.status_code in {400, 422}
    assert response.json()["code"] in {"invalid_argument", "validation_failed"}


def test_broken_template_reports_reason(client_factory, settings) -> None:
    path = settings.workspace_dir / "report-templates" / "broken.yaml"
    path.write_text(
        "name: broken\n"
        "sections:\n"
        "  - id: overview\n"
        "    title: 概览\n"
        "    blocks: [unknown_block]\n",
        encoding="utf-8",
    )
    try:
        client = client_factory([text_step("ok")])
        response = client.post("/api/v1/report-templates/broken/validate")
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "unknown blocks" in detail
    finally:
        path.unlink(missing_ok=True)


def test_reload_counts_templates(client_factory) -> None:
    client = client_factory([text_step("ok")])
    response = client.post("/api/v1/report-templates/reload")
    assert response.status_code == 200
    assert response.json()["templates"] >= 1

