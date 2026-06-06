"""Slack per-task agent lines (SLACK_AGENT_EVENT_UPDATES)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import Settings
from app.slack_digest import (
    SlackSafetyError,
    allowed_slack_channel_ids,
    post_agent_event_to_slack,
    post_text_to_slack,
    slack_agent_event_updates_enabled,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", False),
        ("0", False),
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
    ],
)
def test_slack_agent_event_updates_enabled_parsing(raw: str, expected: bool) -> None:
    s = Settings(slack_agent_event_updates=raw)
    assert slack_agent_event_updates_enabled(s) is expected


def test_post_agent_event_skips_when_disabled() -> None:
    with patch("app.slack_digest.post_text_to_slack") as m:
        post_agent_event_to_slack(
            Settings(
                slack_agent_event_updates="",
                slack_bot_token="xoxb-fake",
                slack_digest_channel_id="C123",
            ),
            agent="Ingest agent",
            detail="test",
        )
        m.assert_not_called()


def test_post_agent_event_skips_without_slack_config() -> None:
    with patch("app.slack_digest.post_text_to_slack") as m:
        post_agent_event_to_slack(
            Settings(slack_agent_event_updates="1", slack_bot_token="", slack_digest_channel_id=""),
            agent="Ingest agent",
            detail="test",
        )
        m.assert_not_called()


def test_post_agent_event_calls_post_text_when_enabled() -> None:
    with patch("app.slack_digest.post_text_to_slack") as m:
        post_agent_event_to_slack(
            Settings(
                slack_agent_event_updates="1",
                slack_bot_token="xoxb-fake",
                slack_digest_channel_id="C123",
            ),
            agent="Ingest agent",
            detail="done",
        )
        m.assert_called_once()
        args, kwargs = m.call_args
        assert "Ingest agent" in kwargs.get("text", "")


def test_allowed_slack_channels_ignore_non_parkinglot_configured_channels() -> None:
    settings = Settings(
        slack_allowed_channel_ids="",
        slack_digest_channel_id="C_DIGEST",
        slack_agent_discussion_channel_id="C_AGENT",
        site_watchdog_slack_channel_id="C_WATCHDOG",
        ops_remediation_slack_channel_id="C_OPS",
    )
    assert allowed_slack_channel_ids(settings) == {"C0B0VPSAH44"}


def test_allowed_slack_channels_default_to_parkinglot_channel() -> None:
    assert allowed_slack_channel_ids(Settings()) == {"C0B0VPSAH44"}


def test_allowed_slack_channels_reject_explicit_non_parkinglot_allowlist() -> None:
    settings = Settings(
        slack_digest_channel_id="C_DIGEST",
        slack_allowed_channel_ids="C_ALLOWED_1, C_ALLOWED_2",
    )
    assert allowed_slack_channel_ids(settings) == set()


def test_allowed_slack_channels_keep_parkinglot_from_explicit_allowlist() -> None:
    settings = Settings(slack_allowed_channel_ids="C_ALLOWED_1, C0B0VPSAH44")
    assert allowed_slack_channel_ids(settings) == {"C0B0VPSAH44"}


def test_post_text_rejects_non_parkinglot_project_before_slack_api() -> None:
    settings = Settings(
        app_project_id="mobile-home-parks",
        slack_bot_token="xoxb-fake",
        slack_digest_channel_id="C_DIGEST",
    )
    with patch("app.slack_digest.WebClient") as client:
        with pytest.raises(SlackSafetyError, match="APP_PROJECT_ID"):
            post_text_to_slack(settings, text="hello")
        client.assert_not_called()


def test_post_text_rejects_channel_outside_allowlist_before_slack_api() -> None:
    settings = Settings(
        app_project_id="parkinglot",
        slack_bot_token="xoxb-fake",
        slack_digest_channel_id="C_DIGEST",
        slack_allowed_channel_ids="C0B0VPSAH44",
    )
    with patch("app.slack_digest.WebClient") as client:
        with pytest.raises(SlackSafetyError, match="not the parkinglot Slack channel"):
            post_text_to_slack(settings, text="hello", channel_id="C_OTHER")
        client.assert_not_called()
