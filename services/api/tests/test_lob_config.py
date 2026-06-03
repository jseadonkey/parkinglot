from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app


def test_lob_status_with_api_key_only() -> None:
    client = TestClient(app)
    with patch(
        "app.routers.internal.get_settings",
        return_value=Settings(lob_api_key="live_secret"),
    ):
        resp = client.get("/internal/lob/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_api_key"] is True
    assert body["lob_test_mode"] is False
    assert body["lob_configured"] is False


def test_lob_verify_success() -> None:
    client = TestClient(app)
    with patch(
        "app.routers.internal.get_settings",
        return_value=Settings(lob_api_key="live_secret"),
    ):
        with patch("app.routers.internal.verify_lob_api_key", return_value=(True, "ok")):
            resp = client.post("/internal/lob/verify")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
