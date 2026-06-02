"""[M0-API-05] Engine /health liveness endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from services.engine.main import app

client = TestClient(app)


def test_health_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "engine"}
