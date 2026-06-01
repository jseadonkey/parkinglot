from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_health_returns_ok_and_version(monkeypatch) -> None:
    monkeypatch.setenv("APP_VERSION", "test")
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "test"
