"""Run the audit crew or a deterministic tools-only preflight (no LLM required)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from parking_crew.env import crew_root, load_crew_env
from parking_crew.regions import default_audit_inputs
from parking_crew.tools import (
    GitHubPRTool,
    NotificationTool,
    ReadDatabaseTool,
    ReadServerLogsTool,
    WebSearchTool,
)


def _output_dir() -> Path:
    out = crew_root() / "output"
    out.mkdir(parents=True, exist_ok=True)
    return out


def run_tools_preflight(
    county_fips: str | None = None,
    *,
    min_score: float = 70.0,
    lookback_hours: int = 168,
) -> dict[str, Any]:
    """
    Exercise every custom tool in agent order. Safe without OPENAI_API_KEY.
    Uses dry-run fallbacks when Slack/GitHub/search credentials are unset.
    """
    load_crew_env()
    inputs = default_audit_inputs(county_fips)
    fips = str(inputs["county_fips"])

    db = ReadDatabaseTool()
    web = WebSearchTool()
    gh = GitHubPRTool()
    logs = ReadServerLogsTool()
    notify = NotificationTool()

    report: dict[str, Any] = {
        "mode": "tools_preflight",
        "inputs": inputs,
        "steps": {},
    }

    for kind in ("zoning_summary", "parcel_sample", "score_summary", "qualified_parcels", "audit_activity"):
        try:
            report["steps"][f"db_{kind}"] = db._run(county_fips=fips, query_kind=kind, min_score=min_score)
        except Exception as exc:
            report["steps"][f"db_{kind}"] = {"error": str(exc)}

    report["steps"]["web_search"] = web._run(
        query=f"{inputs['region_name']} municipal code surface parking principal use ordinance",
        max_results=3,
    )

    report["steps"]["github_pr_draft"] = gh._run(
        title=f"[crew] Scoring calibration draft for {fips}",
        body="Automated tools preflight — no merge intended.",
        file_path="config/pilot_baltimore.yaml",
        new_file_content="# DRAFT — replace via human review\n",
    )

    report["steps"]["server_logs"] = logs._run(lookback_hours=lookback_hours, county_fips=fips)

    report["steps"]["notification"] = notify._run(
        subject=f"Crew tools preflight — {inputs['region_name']}",
        message=f"Preflight completed for FIPS {fips}. Run full crew when OPENAI_API_KEY is set.",
        severity="info",
    )

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = _output_dir() / f"tools_preflight_{fips}_{ts}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["output_file"] = str(out_path)
    return report


def run_full_crew(
    county_fips: str | None = None,
    *,
    lookback_hours: int = 168,
    qualified_score_threshold: float = 70.0,
) -> Any:
    """Run the three-agent CrewAI pipeline (requires OPENAI_API_KEY or configured LLM)."""
    import os

    load_crew_env()
    inputs = default_audit_inputs(county_fips)
    inputs["lookback_hours"] = lookback_hours
    inputs["qualified_score_threshold"] = qualified_score_threshold

    from parking_crew.crew import ParkingAuditCrew
    from parking_crew.observability import (
        flush_langfuse,
        langfuse_crew_trace,
        setup_langfuse_instrumentation,
    )

    setup_langfuse_instrumentation()
    crew_root_path = crew_root()
    previous = os.getcwd()
    try:
        os.chdir(crew_root_path)
        trace_name = f"parking-crew-audit-{inputs['county_fips']}"
        with langfuse_crew_trace(trace_name, metadata={"inputs": inputs}):
            result = ParkingAuditCrew().crew().kickoff(inputs=inputs)
    finally:
        os.chdir(previous)
        flush_langfuse()

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    fips = inputs["county_fips"]
    out_path = _output_dir() / f"crew_audit_{fips}_{ts}.md"
    out_path.write_text(str(result), encoding="utf-8")
    return result
