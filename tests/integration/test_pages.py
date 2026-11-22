from __future__ import annotations

import pytest

from reportify.api.routes.pages import PAGES


@pytest.fixture
def pages_client(client_factory):
    return client_factory([])


def test_root_redirects_to_analysis(pages_client) -> None:
    response = pages_client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/analysis"


@pytest.mark.parametrize("page", sorted(PAGES))
def test_every_page_renders(pages_client, page: str) -> None:
    response = pages_client.get(f"/{page}")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert 'data-view="' + page + '"' in body
    assert PAGES[page] in body
    assert "/static/app.css" in body
    assert f"/static/views/{page}.js" in body
    # the shell carries no user data, so the CSP can stay strict
    assert "<script>" not in body


def test_sidebar_links_all_views(pages_client) -> None:
    body = pages_client.get("/analysis").text
    for page in PAGES:
        assert f'href="/{page}"' in body


def test_static_assets_are_served(pages_client) -> None:
    css = pages_client.get("/static/app.css")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert "--accent" in css.text

    api_js = pages_client.get("/static/api.js")
    assert api_js.status_code == 200
    assert "textContent" in api_js.text
    assert "innerHTML" not in api_js.text


def test_unknown_page_is_404(pages_client) -> None:
    assert pages_client.get("/nope").status_code == 404


def test_pages_do_not_leak_workspace_content(pages_client) -> None:
    body = pages_client.get("/skills").text
    # the Skills page shows a placeholder until JS fetches the API
    assert "选择左侧 Skill 查看全文。" in body
