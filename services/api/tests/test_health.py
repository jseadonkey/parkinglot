from __future__ import annotations

import os

from fastapi.testclient import TestClient

os.environ.setdefault("APP_VERSION", "test")

from app.main import app  # noqa: E402


def test_health_returns_ok_and_version() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "test"
