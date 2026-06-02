from __future__ import annotations

from app.site_watchdog import should_post_slack


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
    report = {"ok": True, "checked_at": "2026-06-02T00:00:00+00:00"}
    previous = {"ok": True, "checked_at": "2026-06-02T00:10:00+00:00"}
    post, _ = should_post_slack(settings, report, previous)
    assert post is False
