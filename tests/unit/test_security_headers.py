from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reportify.api.middleware import CONTENT_SECURITY_POLICY, SecurityHeadersMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/page")
    async def page() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/api/v1/thing")
    async def api() -> dict[str, str]:
        return {"ok": "yes"}

    return app


def test_csp_is_strict() -> None:
    assert "default-src 'self'" in CONTENT_SECURITY_POLICY
    assert "script-src 'self'" in CONTENT_SECURITY_POLICY
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY
    assert "unsafe-eval" not in CONTENT_SECURITY_POLICY
    assert "frame-ancestors 'none'" in CONTENT_SECURITY_POLICY


def test_headers_are_added() -> None:
    with TestClient(_app()) as client:
        response = client.get("/page")
    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_api_responses_are_not_cached() -> None:
    with TestClient(_app()) as client:
        response = client.get("/api/v1/thing")
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("path", ["/page", "/api/v1/thing"])
def test_policy_covers_every_response(path: str) -> None:
    with TestClient(_app()) as client:
        assert client.get(path).headers["Content-Security-Policy"]
