"""
Custom CrewAI tools for the parkinglot audit crew.

Credential / connection setup (copy to services/crew/.env or export in shell):

  # Postgres — same DSN the API uses (deploy/.env DATABASE_URL on the Droplet)
  CREW_DATABASE_URL=postgresql+psycopg://parking:parking@localhost:5432/parking

  # Web search — pick one provider (Serper is common with CrewAI examples)
  SERPER_API_KEY=
  # TAVILY_API_KEY=

  # GitHub — fine-grained PAT with contents:write + pull_requests:write on this repo
  GITHUB_TOKEN=
  GITHUB_REPO=your-org/parkinglot
  GITHUB_BASE_BRANCH=main

  # Server logs / metrics — SSH to the parkinglot Droplet or read local compose logs
  FINOPS_SSH_HOST=parkinglot
  FINOPS_SSH_USER=root
  FINOPS_LOG_COMMAND=docker compose -f deploy/docker-compose.production.yml logs --since 168h api worker
  # Optional: Postgres stats via psql on the server
  FINOPS_DB_STATS_COMMAND=docker compose -f deploy/docker-compose.production.yml exec -T db psql -U parking -d parking -c "SELECT * FROM pg_stat_database WHERE datname='parking';"

  # Slack admin alerts — reuse API tokens (see deploy/env.production.example)
  SLACK_BOT_TOKEN=xoxb-...
  SLACK_ADMIN_CHANNEL_ID=C01234567890

Install deps: pip install crewai psycopg[binary] httpx PyGithub slack-sdk
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from typing import Any

import httpx
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from parking_crew.env import load_crew_env

# ---------------------------------------------------------------------------
# Shared helpers — fill CREW_DATABASE_URL (or DATABASE_URL) before running crew
# ---------------------------------------------------------------------------

_ENGINE: Engine | None = None


def _database_url() -> str:
    load_crew_env()
    url = (os.getenv("CREW_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError(
            "Set CREW_DATABASE_URL or DATABASE_URL "
            "(postgresql+psycopg://user:pass@host:5432/parking)"
        )
    return url


def _get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(_database_url(), pool_pre_ping=True)
    return _ENGINE


def _rows_to_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, default=str, indent=2)


# ---------------------------------------------------------------------------
# ReadDatabaseTool — parcels, scores, rate comps, audit activity
# ---------------------------------------------------------------------------


class ReadDatabaseInput(BaseModel):
    """Query parkinglot Postgres for county-scoped records."""

    county_fips: str = Field(..., description="5-digit county FIPS, e.g. 24510 or 53033")
    query_kind: str = Field(
        default="zoning_summary",
        description=(
            "One of: zoning_summary, parcel_sample, score_summary, "
            "rate_comps, qualified_parcels, audit_activity"
        ),
    )
    limit: int = Field(default=25, ge=1, le=500, description="Row limit for sample queries")
    min_score: float = Field(
        default=70.0,
        ge=0.0,
        le=100.0,
        description="Minimum total_score for qualified_parcels query",
    )


class ReadDatabaseTool(BaseTool):
    name: str = "read_database"
    description: str = (
        "Read scraped parcel, zoning, scoring, and audit data from the parkinglot "
        "Postgres database for a given county FIPS."
    )
    args_schema: type[BaseModel] = ReadDatabaseInput

    def _run(
        self,
        county_fips: str,
        query_kind: str = "zoning_summary",
        limit: int = 25,
        min_score: float = 70.0,
    ) -> str:
        fips = county_fips.strip()
        engine = _get_engine()

        queries: dict[str, tuple[str, dict[str, Any]]] = {
            "zoning_summary": (
                """
                SELECT zoning_code,
                       COUNT(*) AS parcel_count,
                       SUM(CASE WHEN zoning_allows_surface_parking THEN 1 ELSE 0 END) AS allows_surface_count
                FROM parcels
                WHERE county_fips = :fips
                GROUP BY zoning_code
                ORDER BY parcel_count DESC
                LIMIT :limit
                """,
                {"fips": fips, "limit": limit},
            ),
            "parcel_sample": (
                """
                SELECT apn, zoning_code, zoning_allows_surface_parking, lot_sqft,
                       is_corner_lot, distance_to_nearest_demand_m,
                       raw_properties->>'vacancy_indicator' AS vacancy_indicator
                FROM parcels
                WHERE county_fips = :fips
                ORDER BY created_at DESC
                LIMIT :limit
                """,
                {"fips": fips, "limit": limit},
            ),
            "score_summary": (
                """
                SELECT ps.score_profile,
                       COUNT(*) AS n,
                       ROUND(AVG(ps.total_score)::numeric, 2) AS avg_score,
                       ROUND(MAX(ps.total_score)::numeric, 2) AS max_score
                FROM parcel_scores ps
                JOIN parcels p ON p.id = ps.parcel_id
                WHERE p.county_fips = :fips
                GROUP BY ps.score_profile
                """,
                {"fips": fips},
            ),
            "rate_comps": (
                """
                SELECT name,
                       hourly_mid_usd,
                       source_note,
                       ST_Y(location::geometry) AS lat,
                       ST_X(location::geometry) AS lon,
                       active,
                       created_at
                FROM parking_rate_comps
                WHERE active IS TRUE
                ORDER BY created_at DESC
                LIMIT :limit
                """,
                {"limit": limit},
            ),
            "qualified_parcels": (
                """
                SELECT DISTINCT ON (p.apn)
                       p.apn, ps.score_profile, ps.total_score, ps.breakdown, p.lot_sqft
                FROM parcels p
                JOIN parcel_scores ps ON ps.parcel_id = p.id
                WHERE p.county_fips = :fips AND ps.total_score >= :min_score
                ORDER BY p.apn, ps.total_score DESC
                LIMIT :limit
                """,
                {"fips": fips, "min_score": min_score, "limit": limit},
            ),
            "audit_activity": (
                """
                SELECT action, created_at, meta
                FROM audit_log
                WHERE meta->>'county_fips' = :fips
                   OR meta->>'default_county_fips' = :fips
                ORDER BY created_at DESC
                LIMIT :limit
                """,
                {"fips": fips, "limit": limit},
            ),
        }

        if query_kind not in queries:
            return f"Unknown query_kind {query_kind!r}. Choose from: {', '.join(queries)}"

        sql, params = queries[query_kind]
        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            rows = [dict(row._mapping) for row in result]
        return _rows_to_json(rows)


# ---------------------------------------------------------------------------
# WebSearchTool — municipal code / ordinance lookup
# ---------------------------------------------------------------------------


class WebSearchInput(BaseModel):
    query: str = Field(..., description="Search query, e.g. 'Baltimore City Code surface parking principal use Table 10-301'")
    max_results: int = Field(default=5, ge=1, le=10)


class WebSearchTool(BaseTool):
    name: str = "web_search"
    description: str = (
        "Search the public web for official municipal zoning codes, parking ordinances, "
        "and land-use tables when the database lacks up-to-date ordinance text."
    )
    args_schema: type[BaseModel] = WebSearchInput

    def _run(self, query: str, max_results: int = 5) -> str:
        serper_key = (os.getenv("SERPER_API_KEY") or "").strip()
        tavily_key = (os.getenv("TAVILY_API_KEY") or "").strip()

        if serper_key:
            return self._search_serper(query, max_results, serper_key)
        if tavily_key:
            return self._search_tavily(query, max_results, tavily_key)

        return (
            "Web search not configured. Set SERPER_API_KEY or TAVILY_API_KEY in .env.\n"
            f"Stub results for query: {query!r}\n"
            "- https://codes.baltimorecity.gov/ (example municipal code host)\n"
            "- https://library.municode.com/ (example county code host)"
        )

    def _search_serper(self, query: str, max_results: int, api_key: str) -> str:
        # https://serper.dev — Google results API
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
        organic = data.get("organic") or []
        trimmed = [
            {"title": r.get("title"), "link": r.get("link"), "snippet": r.get("snippet")}
            for r in organic[:max_results]
        ]
        return _rows_to_json(trimmed)

    def _search_tavily(self, query: str, max_results: int, api_key: str) -> str:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": query, "max_results": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
        return json.dumps(data.get("results") or [], indent=2)


# ---------------------------------------------------------------------------
# GitHubPRTool — propose scoring / revenue config changes
# ---------------------------------------------------------------------------


class GitHubPRInput(BaseModel):
    title: str = Field(..., description="Pull request title")
    body: str = Field(..., description="PR description with rationale and test plan")
    file_path: str = Field(
        ...,
        description="Repo-relative path, e.g. config/pilot.yaml or config/pilot_baltimore.yaml",
    )
    branch_name: str = Field(
        default="",
        description="Optional branch name; auto-generated when empty",
    )
    new_file_content: str = Field(
        ...,
        description="Full proposed file contents after your YAML edits",
    )


class GitHubPRTool(BaseTool):
    name: str = "github_pr"
    description: str = (
        "Open a GitHub pull request proposing changes to scoring or revenue "
        "configuration files (config/pilot*.yaml). Requires GITHUB_TOKEN."
    )
    args_schema: type[BaseModel] = GitHubPRInput

    def _run(
        self,
        title: str,
        body: str,
        file_path: str,
        new_file_content: str,
        branch_name: str = "",
    ) -> str:
        token = (os.getenv("GITHUB_TOKEN") or "").strip()
        repo_name = (os.getenv("GITHUB_REPO") or "").strip()
        base_branch = (os.getenv("GITHUB_BASE_BRANCH") or "main").strip()

        if not token or not repo_name:
            return (
                "GitHub PR not configured. Set GITHUB_TOKEN and GITHUB_REPO (org/repo).\n"
                f"DRAFT PR:\n  title: {title}\n  file: {file_path}\n  body:\n{body}\n"
                f"  content_bytes: {len(new_file_content)}"
            )

        try:
            from github import Github  # PyGithub — install with: pip install PyGithub
        except ImportError:
            return "Install PyGithub: pip install PyGithub"

        gh = Github(token)
        repo = gh.get_repo(repo_name)
        ts = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S")
        branch = branch_name.strip() or f"crew/scoring-adjustment-{ts}"
        base_ref = repo.get_git_ref(f"heads/{base_branch}")
        repo.create_git_ref(ref=f"refs/heads/{branch}", sha=base_ref.object.sha)

        try:
            existing = repo.get_contents(file_path, ref=branch)
            repo.update_file(
                path=file_path,
                message=title,
                content=new_file_content,
                sha=existing.sha,
                branch=branch,
            )
        except Exception:
            repo.create_file(
                path=file_path,
                message=title,
                content=new_file_content,
                branch=branch,
            )

        pr = repo.create_pull(title=title, body=body, head=branch, base=base_branch)
        return json.dumps({"status": "created", "url": pr.html_url, "branch": branch}, indent=2)


# ---------------------------------------------------------------------------
# ReadServerLogsTool — Droplet / compose logs and optional DB stats
# ---------------------------------------------------------------------------


class ReadServerLogsInput(BaseModel):
    lookback_hours: int = Field(default=168, ge=1, le=720, description="Hours of logs/metrics to summarize")
    county_fips: str = Field(default="", description="Optional FIPS filter when parsing audit/meta lines")


class ReadServerLogsTool(BaseTool):
    name: str = "read_server_logs"
    description: str = (
        "Fetch server usage signals: Docker compose logs, optional Postgres stats, "
        "and ingest/scoring activity. Configure FINOPS_SSH_HOST or FINOPS_LOG_COMMAND."
    )
    args_schema: type[BaseModel] = ReadServerLogsInput

    def _run(self, lookback_hours: int = 168, county_fips: str = "") -> str:
        log_cmd = (os.getenv("FINOPS_LOG_COMMAND") or "").strip()
        db_stats_cmd = (os.getenv("FINOPS_DB_STATS_COMMAND") or "").strip()
        ssh_host = (os.getenv("FINOPS_SSH_HOST") or "").strip()
        ssh_user = (os.getenv("FINOPS_SSH_USER") or "root").strip()

        if not log_cmd and not db_stats_cmd:
            return json.dumps(
                {
                    "lookback_hours": lookback_hours,
                    "county_fips_filter": county_fips or None,
                    "status": "not_configured",
                    "message": (
                        "Set FINOPS_LOG_COMMAND (local) or FINOPS_SSH_HOST + FINOPS_LOG_COMMAND "
                        "(remote via SSH)."
                    ),
                    "example_finops_log_command": (
                        "docker compose -f deploy/docker-compose.production.yml logs "
                        f"--since {lookback_hours}h api worker beat"
                    ),
                },
                indent=2,
            )

        output: dict[str, Any] = {"lookback_hours": lookback_hours, "county_fips_filter": county_fips or None}

        if log_cmd:
            output["compose_logs"] = self._run_shell(log_cmd, ssh_host, ssh_user, lookback_hours)

        if db_stats_cmd:
            output["db_stats"] = self._run_shell(db_stats_cmd, ssh_host, ssh_user, lookback_hours)

        # Lightweight local fallback: count audit rows if DB is reachable
        try:
            engine = _get_engine()
            with engine.connect() as conn:
                n = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM audit_log "
                        "WHERE created_at >= NOW() - (:hours || ' hours')::interval"
                    ),
                    {"hours": str(lookback_hours)},
                ).scalar_one()
            output["audit_log_rows_in_window"] = int(n)
        except Exception as exc:
            output["audit_log_rows_in_window_error"] = str(exc)

        return json.dumps(output, indent=2)

    def _run_shell(
        self,
        command_template: str,
        ssh_host: str,
        ssh_user: str,
        lookback_hours: int,
    ) -> str:
        command = command_template.replace("{lookback_hours}", str(lookback_hours))
        if ssh_host:
            # SSH alias "parkinglot" is valid if configured in ~/.ssh/config
            remote_cmd = f"cd /opt/workspaces/parkinglot && {command}"
            full = ["ssh", f"{ssh_user}@{ssh_host}", remote_cmd]
        else:
            full = ["bash", "-lc", command]

        proc = subprocess.run(
            full,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        stdout = (proc.stdout or "")[-8000:]
        stderr = (proc.stderr or "")[-2000:]
        if proc.returncode != 0:
            return f"exit={proc.returncode}\nstderr:\n{stderr}\nstdout:\n{stdout}"
        return stdout or "(empty stdout)"


# ---------------------------------------------------------------------------
# NotificationTool — Slack admin alert
# ---------------------------------------------------------------------------


class NotificationInput(BaseModel):
    subject: str = Field(..., description="Short alert subject line")
    message: str = Field(..., description="Markdown-ish body with ROI findings and recommended action")
    severity: str = Field(default="warning", description="info | warning | critical")


class NotificationTool(BaseTool):
    name: str = "notify_admin"
    description: str = (
        "Send a Slack message to the human admin when infrastructure spend "
        "does not match business value. Requires SLACK_BOT_TOKEN and SLACK_ADMIN_CHANNEL_ID."
    )
    args_schema: type[BaseModel] = NotificationInput

    def _run(self, subject: str, message: str, severity: str = "warning") -> str:
        token = (os.getenv("SLACK_BOT_TOKEN") or "").strip()
        channel = (os.getenv("SLACK_ADMIN_CHANNEL_ID") or os.getenv("SLACK_DIGEST_CHANNEL_ID") or "").strip()

        if not token or not channel:
            return (
                "Slack not configured. Set SLACK_BOT_TOKEN and SLACK_ADMIN_CHANNEL_ID "
                "(or SLACK_DIGEST_CHANNEL_ID).\n"
                f"DRY RUN [{severity}] {subject}\n{message}"
            )

        emoji = {"info": ":information_source:", "warning": ":warning:", "critical": ":rotating_light:"}.get(
            severity, ":warning:"
        )
        text = f"{emoji} *{subject}*\n{message}"
        client = WebClient(token=token)
        try:
            resp = client.chat_postMessage(channel=channel, text=text, mrkdwn=True)
            return json.dumps({"status": "sent", "channel": channel, "ts": resp.get("ts")}, indent=2)
        except SlackApiError as exc:
            return json.dumps({"status": "error", "error": str(exc)}, indent=2)


# ---------------------------------------------------------------------------
# Tool bundles — import these lists when constructing CrewAI Agent instances
# ---------------------------------------------------------------------------

ZONING_ANALYST_TOOLS = [ReadDatabaseTool(), WebSearchTool()]
REVENUE_ACTUARY_TOOLS = [ReadDatabaseTool(), GitHubPRTool()]
FINOPS_COMPTROLLER_TOOLS = [ReadServerLogsTool(), NotificationTool()]
