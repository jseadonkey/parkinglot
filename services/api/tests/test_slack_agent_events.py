"""Slack per-task agent lines (SLACK_AGENT_EVENT_UPDATES)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import Settings
from app.slack_digest import post_agent_event_to_slack, slack_agent_event_updates_enabled


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
