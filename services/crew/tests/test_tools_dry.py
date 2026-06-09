"""Tool dry-run tests — no Postgres, Slack, GitHub, or LLM required."""

from __future__ import annotations

import json
from pathlib import Path

from parking_crew.kickoff import run_tools_preflight
from parking_crew.tools import GitHubPRTool, NotificationTool, ReadServerLogsTool, WebSearchTool


def test_web_search_without_api_key_returns_stub() -> None:
    out = WebSearchTool()._run(query="Baltimore City Code parking", max_results=3)
    assert "Baltimore" in out or "Stub" in out or "not configured" in out


def test_github_pr_without_token_returns_draft() -> None:
    out = GitHubPRTool()._run(
        title="test",
        body="body",
        file_path="config/pilot.yaml",
        new_file_content="x: 1\n",
    )
    assert "DRAFT PR" in out or "not configured" in out


def test_notification_without_slack_dry_runs() -> None:
    out = NotificationTool()._run(subject="test", message="hello", severity="info")
    assert "DRY RUN" in out or "not configured" in out


def test_server_logs_without_command_returns_help() -> None:
    out = ReadServerLogsTool()._run(lookback_hours=24)
    parsed = json.loads(out)
    assert parsed["lookback_hours"] == 24
    assert parsed.get("status") == "not_configured" or "compose_logs" in parsed


def test_tools_preflight_writes_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("parking_crew.kickoff._output_dir", lambda: tmp_path)
    report = run_tools_preflight("24510", lookback_hours=24)
    assert report["mode"] == "tools_preflight"
    assert report["inputs"]["county_fips"] == "24510"
    out_path = Path(report["output_file"])
    assert out_path.is_file()
    assert out_path.parent == tmp_path
