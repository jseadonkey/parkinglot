from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.site_watchdog import _api_base_url, _ui_base_url, should_post_slack


def test_api_base_prefers_internal() -> None:
    settings = Settings(
        site_watchdog_internal_api_url="http://api:8000",
        api_public_url="https://api.example.com",
    )
    assert _api_base_url(settings) == "http://api:8000"


def test_api_base_uses_public_when_not_localhost() -> None:
    settings = Settings(api_public_url="https://api.example.com")
    assert _api_base_url(settings) == "https://api.example.com"


def test_api_base_falls_back_to_docker_service() -> None:
    settings = Settings()
    assert _api_base_url(settings) == "http://api:8000"


def test_ui_base_prefers_explicit() -> None:
    settings = Settings(
        site_watchdog_ui_base_url="https://vspecialist.com",
        cors_allow_origins="https://other.example.com",
    )
    assert _ui_base_url(settings) == "https://vspecialist.com"


def test_ui_base_uses_cors_origin() -> None:
    settings = Settings(cors_allow_origins="https://vspecialist.com,https://other.example.com")
    assert _ui_base_url(settings) == "https://vspecialist.com"


def test_ui_base_falls_back_to_operator_console() -> None:
    settings = Settings()
    assert _ui_base_url(settings) == "http://operator-console:3000"


def test_should_post_on_failure() -> None:
    settings = type("S", (), {"site_watchdog_heartbeat_hours": 12})()
    report = {"ok": False, "failure_count": 1}
    post, recovered = should_post_slack(settings, report, {"ok": True})
    assert post is True
    assert recovered is False


def test_should_post_on_recovery() -> None:
    settings = type("S", (), {"site_watchdog_heartbeat_hours": 12})()
    report = {"ok": True, "failure_count": 0}
    post, recovered = should_post_slack(settings, report, {"ok": False})
    assert post is True
    assert recovered is True


def test_should_not_spam_when_still_ok() -> None:
    settings = type("S", (), {"site_watchdog_heartbeat_hours": 12})()
    now = datetime.now(tz=UTC)
    report = {"ok": True, "checked_at": now.isoformat()}
    previous = {"ok": True, "checked_at": (now - timedelta(hours=1)).isoformat()}
    post, _ = should_post_slack(settings, report, previous)
    assert post is False
