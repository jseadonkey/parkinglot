"""GET /internal/slack/status reporting catalog."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_slack_status_includes_reporting_catalog(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_DIGEST_CHANNEL_ID", "C_DIGEST")
    monkeypatch.setenv("SITE_WATCHDOG_ENABLED", "true")
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.get("/internal/slack/status")
    assert response.status_code == 200
    body = response.json()
    assert "reporting_catalog" in body
    assert body["site_watchdog_enabled"] is True
    ids = {row["id"] for row in body["reporting_catalog"]}
    assert "standup" in ids
    assert "site_watchdog" in ids
