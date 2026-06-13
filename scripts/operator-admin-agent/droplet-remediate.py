#!/usr/bin/env python3
"""Compare operator-admin metrics vs previous snapshot and apply safe Droplet remediations."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT_DIR = ROOT / "data" / "operator-agent"
STAGNANT_HOURS = float(os.environ.get("OPERATOR_AGENT_STAGNANT_HOURS", "24"))

METRIC_KEYS = [
    "score_gaps",
    "high_value_remaining",
    "deals_failed",
    "wa_counties_loaded",
    "wa_last_county_parcels",
    "counties_zero_grab_count",
    "wa_counties_remaining",
]

BACKLOG_ITEM_KEYS = [
    "baltimore_property_addresses",
    "wa_property_addresses",
    "pipeline_funnel",
    "score_gaps",
    "owner_outreach_briefs",
]


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _hours_between(prev_at: str | None, now_at: str) -> float | None:
    prev = _parse_ts(prev_at)
    now = _parse_ts(now_at)
    if not prev or not now:
        return None
    return max(0.0, (now - prev).total_seconds() / 3600.0)


def detect_stagnation(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Flag metrics that did not improve over the stagnation window."""
    if not previous:
        return []

    now_at = str(current.get("checked_at") or "")
    prev_at = str(previous.get("checked_at") or "")
    hours = _hours_between(prev_at, now_at)
    if hours is None or hours < STAGNANT_HOURS:
        return []

    out: list[dict[str, Any]] = []
    cur_m = current.get("metrics") if isinstance(current.get("metrics"), dict) else {}
    prev_m = previous.get("metrics") if isinstance(previous.get("metrics"), dict) else {}

    score = int(cur_m.get("score_gaps") or 0)
    prev_score = int(prev_m.get("score_gaps") or 0)
    if score >= 1_000 and score >= prev_score:
        out.append(
            {
                "metric": "score_gaps",
                "previous": prev_score,
                "current": score,
                "hours": round(hours, 1),
                "detail": "Identification/entitlement score gaps not draining",
            }
        )

    hv = int(cur_m.get("high_value_remaining") or 0)
    prev_hv = int(prev_m.get("high_value_remaining") or 0)
    if hv > 0 and hv >= prev_hv:
        out.append(
            {
                "metric": "high_value_remaining",
                "previous": prev_hv,
                "current": hv,
                "hours": round(hours, 1),
                "detail": "High-value backlog not decreasing",
            }
        )

    cur_items = cur_m.get("backlog_items") if isinstance(cur_m.get("backlog_items"), dict) else {}
    prev_items = prev_m.get("backlog_items") if isinstance(prev_m.get("backlog_items"), dict) else {}
    for key in BACKLOG_ITEM_KEYS:
        cur_v = int(cur_items.get(key) or 0)
        prev_v = int(prev_items.get(key) or 0)
        if cur_v <= 0:
            continue
        if cur_v >= prev_v and key != "owner_outreach_briefs":
            out.append(
                {
                    "metric": f"backlog.{key}",
                    "previous": prev_v,
                    "current": cur_v,
                    "hours": round(hours, 1),
                    "detail": f"Backlog row {key} not shrinking",
                }
            )

    snap_at = str(cur_m.get("data_snapshot_at") or "")
    snap_age_h: float | None = None
    snap_dt = _parse_ts(snap_at)
    if snap_dt:
        snap_age_h = (datetime.now(UTC) - snap_dt).total_seconds() / 3600.0
    if snap_age_h is not None and snap_age_h > 6:
        out.append(
            {
                "metric": "ops_snapshot_stale",
                "previous": snap_at,
                "current": snap_at,
                "hours": round(snap_age_h, 1),
                "detail": "Ops remediation snapshot older than 6h",
            }
        )

    wa_loaded = int(cur_m.get("wa_counties_loaded") or 0)
    prev_wa = int(prev_m.get("wa_counties_loaded") or 0)
    wa_parcels = int(cur_m.get("wa_last_county_parcels") or 0)
    if hours >= 12 and wa_loaded == prev_wa and wa_parcels == 0 and cur_m.get("wa_next_county_fips"):
        out.append(
            {
                "metric": "wa_county_stuck",
                "previous": prev_wa,
                "current": wa_loaded,
                "hours": round(hours, 1),
                "detail": f"WA next county {cur_m.get('wa_next_county_fips')} still has 0 parcels",
            }
        )

    return out


def detect_scrape_gaps(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Counties configured in pilot scope but with 0 parcels ingested (not yet grabbed)."""
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    gaps = metrics.get("scrape_gaps")
    if not isinstance(gaps, list):
        coverage = report.get("scrape_coverage")
        if isinstance(coverage, dict):
            gaps = coverage.get("scrape_gaps")
    if not isinstance(gaps, list):
        return []

    out: list[dict[str, Any]] = []
    for row in gaps:
        if not isinstance(row, dict):
            continue
        if int(row.get("parcels_in_db") or 0) > 0:
            continue
        out.append(
            {
                "county_fips": str(row.get("county_fips") or ""),
                "county_name": str(row.get("county_name") or ""),
                "kind": str(row.get("kind") or "wa_rollout_pending"),
                "priority_market": bool(row.get("priority_market")),
            }
        )
    return out


def backlog_ready_for_county_rollout(metrics: dict[str, Any]) -> bool:
    """True when high-value work is done and we should pace into the next counties."""
    if metrics.get("should_advance_counties"):
        return True
    if not metrics.get("backlog_complete"):
        return False
    return int(metrics.get("wa_counties_remaining") or 0) > 0


def _compose_cmd() -> list[str]:
    rel = os.environ.get("COMPOSE_REL", "deploy/docker-compose.production.yml")
    return ["docker", "compose", "-f", rel, "--env-file", "deploy/.env"]


def _run(cmd: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def _internal_key() -> str:
    env_path = ROOT / "deploy" / ".env"
    if not env_path.is_file():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("INTERNAL_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def _api_post(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    import base64

    body = json.dumps(payload or {})
    body_b64 = base64.b64encode(body.encode()).decode()
    path_json = json.dumps(path)
    script = f"""
import base64, json, os, urllib.error, urllib.request
path = {path_json}
raw = base64.b64decode({json.dumps(body_b64)}).decode()
key = (os.environ.get("INTERNAL_API_KEY") or "").strip()
headers = {{"Accept": "application/json", "Content-Type": "application/json"}}
if key:
    headers["X-Internal-Key"] = key
req = urllib.request.Request(f"http://127.0.0.1:8000{{path}}", data=raw.encode(), method="POST", headers=headers)
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        print(resp.read().decode())
except urllib.error.HTTPError as exc:
    print(exc.read().decode() if exc.fp else str(exc))
except Exception as exc:
    print(json.dumps({{"error": str(exc)}}))
"""
    code, out = _run(
        [
            *_compose_cmd(),
            "exec",
            "-T",
            "-e",
            f"INTERNAL_API_KEY={_internal_key()}",
            "api",
            "python",
            "-c",
            script,
        ]
    )
    if code != 0:
        return {"error": out or f"exit {code}"}
    try:
        return json.loads(out) if out else {}
    except json.JSONDecodeError:
        return {"raw": out}


def remediate(
    report: dict[str, Any],
    stagnation: list[dict[str, Any]],
    scrape_gaps: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    gaps = scrape_gaps if scrape_gaps is not None else detect_scrape_gaps(report)

    needs_console_restart = any(
        "HTTP 503" in str(i.get("detail", ""))
        or "HTTP 502" in str(i.get("detail", ""))
        or "still showing loading" in str(i.get("detail", ""))
        for i in issues
        if isinstance(i, dict)
    )
    if needs_console_restart:
        code, out = _run([*_compose_cmd(), "up", "-d", "--no-deps", "operator-console"])
        actions.append(
            {
                "action": "restart_operator_console",
                "status": "ok" if code == 0 else "failed",
                "detail": out[:500],
            }
        )

    if any("NoSuchBucket" in str(i.get("detail", "")) for i in issues if isinstance(i, dict)):
        script = """
from app.config import get_settings
import boto3
from botocore.config import Config
s = get_settings()
client = boto3.client(
    "s3",
    endpoint_url=s.storage_endpoint,
    aws_access_key_id=s.storage_access_key,
    aws_secret_access_key=s.storage_secret_key,
    region_name=s.storage_region,
    config=Config(signature_version="s3v4"),
)
try:
    client.head_bucket(Bucket=s.storage_bucket)
    print("bucket_exists")
except Exception:
    client.create_bucket(Bucket=s.storage_bucket)
    print("bucket_created")
"""
        code, out = _run([*_compose_cmd(), "exec", "-T", "api", "python", "-c", script])
        actions.append(
            {
                "action": "ensure_storage_bucket",
                "status": "ok" if code == 0 else "failed",
                "detail": out[:300],
            }
        )

    needs_ops = bool(stagnation) or any(
        s.get("metric") in ("ops_snapshot_stale", "score_gaps", "high_value_remaining")
        or str(s.get("metric", "")).startswith("backlog.")
        for s in stagnation
    )
    if needs_ops:
        result = _api_post("/internal/ops/run-now")
        actions.append(
            {
                "action": "ops_remediation_run_now",
                "status": "ok" if "error" not in result else "failed",
                "detail": json.dumps(result)[:500],
            }
        )

    wa_rollout_needed = (
        any(s.get("metric") == "wa_county_stuck" for s in stagnation)
        or backlog_ready_for_county_rollout(metrics)
        or any(g.get("kind") == "wa_rollout_next" for g in gaps)
    )
    if wa_rollout_needed and metrics.get("wa_rollout_enabled", True):
        governor_ok = metrics.get("wa_rollout_allowed", True) is not False
        cooldown_ok = bool(metrics.get("wa_cooldown_ready")) or backlog_ready_for_county_rollout(metrics)
        queue_ok = int(metrics.get("parking_queue_depth") or 0) < 80_000
        if governor_ok and cooldown_ok and queue_ok:
            result = _api_post("/internal/ingest/wa-rollout-now")
            actions.append(
                {
                    "action": "wa_rollout_now",
                    "status": "ok" if "error" not in result else "failed",
                    "detail": json.dumps(result)[:500],
                }
            )
        else:
            actions.append(
                {
                    "action": "wa_rollout_now",
                    "status": "skipped",
                    "detail": json.dumps(
                        {
                            "governor_ok": governor_ok,
                            "cooldown_ok": cooldown_ok,
                            "queue_ok": queue_ok,
                            "wa_counties_remaining": metrics.get("wa_counties_remaining"),
                        }
                    )[:500],
                }
            )

    priority_zero = [g for g in gaps if g.get("kind") == "pilot_priority"]
    for gap in priority_zero:
        fips = str(gap.get("county_fips") or "")
        if fips == "24510":
            result = _api_post("/internal/ingest/baltimore-city", {"auto_run_pipeline": True, "max_auto_pipeline": 50})
            actions.append(
                {
                    "action": "baltimore_city_ingest",
                    "status": "ok" if "error" not in result else "failed",
                    "detail": json.dumps(result)[:500],
                }
            )
        elif fips == "24005":
            result = _api_post(
                "/internal/ingest/baltimore-county",
                {"auto_run_pipeline": True, "max_auto_pipeline": 50},
            )
            actions.append(
                {
                    "action": "baltimore_county_ingest",
                    "status": "ok" if "error" not in result else "failed",
                    "detail": json.dumps(result)[:500],
                }
            )

    if int(metrics.get("score_gaps") or 0) > 50_000 and stagnation:
        result = _api_post("/internal/pipeline/enqueue-unscored?limit=50")
        actions.append(
            {
                "action": "enqueue_unscored_batch",
                "status": "ok" if "error" not in result else "failed",
                "detail": json.dumps(result)[:500],
            }
        )

    governor = str(metrics.get("load_governor_level") or "")
    if governor in ("orange", "red") and int(metrics.get("parking_queue_depth") or 0) == 0:
        script = """
from app.config import get_settings
from app.tasks import load_governor_refresh
load_governor_refresh.delay()
print("governor_refresh_enqueued")
"""
        code, out = _run([*_compose_cmd(), "exec", "-T", "api", "python", "-c", script])
        actions.append(
            {
                "action": "load_governor_refresh",
                "status": "ok" if code == 0 else "failed",
                "detail": out[:200],
            }
        )

    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Operator admin agent — compare metrics and remediate")
    parser.add_argument("--report", type=Path, default=Path("agent-report.json"))
    parser.add_argument("--previous", type=Path, default=DEFAULT_SNAPSHOT_DIR / "last-snapshot.json")
    parser.add_argument("--write-snapshot", action="store_true", help="Persist current report as last-snapshot.json")
    parser.add_argument("--skip-remediate", action="store_true")
    args = parser.parse_args()

    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    report = _load_json(report_path)
    if not report:
        print(f"Missing report: {report_path}", file=sys.stderr)
        return 1

    previous_path = args.previous if args.previous.is_absolute() else ROOT / args.previous
    previous = _load_json(previous_path)
    stagnation = detect_stagnation(report, previous)
    scrape_gaps = detect_scrape_gaps(report)
    report["stagnation"] = stagnation
    report["scrape_gaps"] = scrape_gaps

    actions: list[dict[str, Any]] = []
    blocking = int(report.get("blocking_issue_count") or 0)
    if blocking == 0 and int(report.get("issue_count") or 0) > 0:
        blocking = sum(
            1
            for i in (report.get("issues") or [])
            if isinstance(i, dict) and i.get("severity") != "warning"
        )
    has_blocking = blocking > 0
    county_rollout = backlog_ready_for_county_rollout(
        report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    )
    needs_remediate = has_blocking or bool(stagnation) or bool(scrape_gaps) or county_rollout
    if not args.skip_remediate and needs_remediate:
        actions = remediate(report, stagnation, scrape_gaps)
    report["remediation"] = actions

    if args.write_snapshot:
        previous_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "checked_at": report.get("checked_at"),
            "metrics": report.get("metrics"),
            "issue_count": report.get("issue_count"),
            "scrape_gaps": scrape_gaps,
        }
        previous_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote snapshot {previous_path}")

    out_path = report_path.parent / "agent-remediation.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"stagnation": stagnation, "remediation": actions}, indent=2))

    if blocking > 0 and not actions:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
