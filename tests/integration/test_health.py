from __future__ import annotations

from fastapi.testclient import TestClient

from reportify.api.app import create_app
from reportify.core.config import Settings


def test_health_returns_ok(settings: Settings) -> None:
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}
