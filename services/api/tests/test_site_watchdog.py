from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.site_watchdog import _api_base_url, _ui_base_url, should_post_slack
from app.tasks import site_watchdog_check


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
    settings = type("S", (), {"site_watchdog_heartbeat_hours": 12, "site_watchdog_failure_repeat_hours": 6})()
    report = {"ok": False, "failure_count": 1}
    post, recovered = should_post_slack(settings, report, {"ok": True})
    assert post is True
    assert recovered is False


def test_should_not_repeat_same_watchdog_failure_inside_repeat_window() -> None:
    settings = type("S", (), {"site_watchdog_heartbeat_hours": 1, "site_watchdog_failure_repeat_hours": 6})()
    now = datetime.now(tz=UTC)
    previous = {
        "ok": False,
        "checked_at": (now - timedelta(hours=1)).isoformat(),
        "checks": [{"name": "operator_ui", "source": "droplet", "ok": False, "detail": "HTTP 502"}],
    }
    report = {
        "ok": False,
        "checked_at": now.isoformat(),
        "checks": [{"name": "operator_ui", "source": "droplet", "ok": False, "detail": "HTTP 502"}],
    }
    post, recovered = should_post_slack(settings, report, previous)
    assert post is False
    assert recovered is False


def test_should_post_when_watchdog_failure_changes() -> None:
    settings = type("S", (), {"site_watchdog_heartbeat_hours": 1, "site_watchdog_failure_repeat_hours": 6})()
    now = datetime.now(tz=UTC)
    previous = {
        "ok": False,
        "checked_at": (now - timedelta(hours=1)).isoformat(),
        "checks": [{"name": "operator_ui", "source": "droplet", "ok": False, "detail": "HTTP 502"}],
    }
    report = {
        "ok": False,
        "checked_at": now.isoformat(),
        "checks": [{"name": "postgres", "source": "droplet", "ok": False, "detail": "timeout"}],
    }
    post, recovered = should_post_slack(settings, report, previous)
    assert post is True
    assert recovered is False


def test_should_repeat_same_watchdog_failure_after_repeat_window() -> None:
    settings = type("S", (), {"site_watchdog_heartbeat_hours": 1, "site_watchdog_failure_repeat_hours": 6})()
    now = datetime.now(tz=UTC)
    previous = {
        "ok": False,
        "checked_at": (now - timedelta(hours=7)).isoformat(),
        "checks": [{"name": "operator_ui", "source": "droplet", "ok": False, "detail": "HTTP 502"}],
    }
    report = {
        "ok": False,
        "checked_at": now.isoformat(),
        "checks": [{"name": "operator_ui", "source": "droplet", "ok": False, "detail": "HTTP 502"}],
    }
    post, recovered = should_post_slack(settings, report, previous)
    assert post is True
    assert recovered is False


def test_should_post_on_recovery() -> None:
    settings = type("S", (), {"site_watchdog_heartbeat_hours": 12, "site_watchdog_failure_repeat_hours": 6})()
    report = {"ok": True, "failure_count": 0}
    post, recovered = should_post_slack(settings, report, {"ok": False})
    assert post is True
    assert recovered is True


def test_should_not_spam_when_still_ok() -> None:
    settings = type("S", (), {"site_watchdog_heartbeat_hours": 12, "site_watchdog_failure_repeat_hours": 6})()
    now = datetime.now(tz=UTC)
    report = {"ok": True, "checked_at": now.isoformat()}
    previous = {"ok": True, "checked_at": (now - timedelta(hours=1)).isoformat()}
    post, _ = should_post_slack(settings, report, previous)
    assert post is False


def test_watchdog_runs_without_slack_configuration() -> None:
    settings = SimpleNamespace(
        slack_bot_token="",
        site_watchdog_slack_channel_id="",
        slack_agent_discussion_channel_id="",
        slack_digest_channel_id="",
    )
    db = MagicMock()
    report = {"ok": True, "failure_count": 0, "checks": []}

    with (
        patch("app.tasks.get_settings", return_value=settings),
        patch("app.tasks._session", return_value=db),
        patch("app.site_watchdog.load_last_report", return_value=None),
        patch("app.site_watchdog.run_droplet_watchdog", return_value=report) as run_watchdog,
        patch("app.site_watchdog.should_post_slack", return_value=(True, False)),
        patch("app.tasks.post_text_to_slack") as post_text,
    ):
        out = site_watchdog_check()

    assert out == {"skipped": False, "ok": True, "posted": False, "slack_configured": False}
    run_watchdog.assert_called_once_with(db)
    post_text.assert_not_called()
    db.close.assert_called_once()
