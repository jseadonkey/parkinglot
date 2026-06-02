"""Site + server health checks (uptime), separate from pipeline Slack digests."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

REDIS_STATE_KEY = "site_watchdog:last"
REDIS_ALERT_COOLDOWN_KEY = "site_watchdog:alert_cooldown"


@dataclass
class WatchdogCheck:
    name: str
    ok: bool
    detail: str
    latency_ms: float | None = None
    source: str = "droplet"  # droplet | github


def _http_get(url: str, *, timeout: float = 20.0) -> tuple[int, str, float]:
    started = time.perf_counter()
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "parking-site-watchdog/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            elapsed_ms = (time.perf_counter() - started) * 1000
            return resp.status, body, elapsed_ms
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        body = exc.read(4096).decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body, elapsed_ms
    except urllib.error.URLError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return 0, str(exc.reason or exc), elapsed_ms


def _ui_base_url(settings: Settings) -> str:
    explicit = (getattr(settings, "site_watchdog_ui_base_url", None) or "").strip()
    if explicit:
        return explicit.rstrip("/")
    # Fallback: first CORS origin (production UI) or localhost dev.
    raw = (settings.cors_allow_origins or "").strip()
    if raw:
        first = raw.split(",")[0].strip()
        if first:
            return first.rstrip("/")
    return "http://127.0.0.1:3000"


def run_public_http_checks(settings: Settings, *, source: str = "droplet") -> list[WatchdogCheck]:
    api_base = (settings.api_public_url or "http://localhost:8000").rstrip("/")
    ui_base = _ui_base_url(settings)
    checks: list[WatchdogCheck] = []

    for path, label in (("/health", "api_health"), ("/ready", "api_ready")):
        status, body, ms = _http_get(f"{api_base}{path}")
        ok = status == 200 and '"status"' in body
        if path == "/ready":
            ok = ok and '"ready"' in body
        detail = f"HTTP {status}" if status else body[:200]
        if not ok and status == 200:
            detail = f"unexpected body: {body[:120]}"
        checks.append(WatchdogCheck(name=label, ok=ok, detail=detail, latency_ms=round(ms, 1), source=source))

    operator_url = f"{ui_base}/operator"
    status, body, ms = _http_get(operator_url, timeout=25.0)
    ok = status in (200, 302, 307, 308) and status != 0
    if status == 200 and ("502 Bad Gateway" in body or "503 Service" in body):
        ok = False
        detail = "operator page returned gateway error in body"
    else:
        detail = f"HTTP {status}" if status else body[:200]
    checks.append(
        WatchdogCheck(name="operator_ui", ok=ok, detail=f"{operator_url} — {detail}", latency_ms=round(ms, 1), source=source)
    )

    return checks


def run_server_checks(
    db: Session,
    settings: Settings,
    *,
    source: str = "droplet",
) -> list[WatchdogCheck]:
    checks: list[WatchdogCheck] = []

    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        ms = (time.perf_counter() - started) * 1000
        checks.append(WatchdogCheck(name="postgres", ok=True, detail="SELECT 1 ok", latency_ms=round(ms, 1), source=source))
    except Exception as exc:
        checks.append(WatchdogCheck(name="postgres", ok=False, detail=str(exc)[:240], source=source))

    try:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        started = time.perf_counter()
        client.ping()
        parking_len = int(client.llen("parking") or 0)
        slack_len = int(client.llen("slack") or 0)
        info = client.info("memory")
        used_mb = round(int(info.get("used_memory", 0)) / (1024 * 1024), 1)
        ms = (time.perf_counter() - started) * 1000
        warn = settings.site_watchdog_parking_queue_warn
        queue_ok = parking_len < warn
        checks.append(
            WatchdogCheck(
                name="redis",
                ok=True,
                detail=f"ping ok · parking queue {parking_len} · slack {slack_len} · mem {used_mb} MiB",
                latency_ms=round(ms, 1),
                source=source,
            )
        )
        checks.append(
            WatchdogCheck(
                name="celery_parking_queue",
                ok=queue_ok,
                detail=f"LLEN parking={parking_len} (warn ≥{warn})",
                source=source,
            )
        )
    except Exception as exc:
        checks.append(WatchdogCheck(name="redis", ok=False, detail=str(exc)[:240], source=source))

    return checks


def build_report(
    checks: list[WatchdogCheck],
    *,
    runner: str,
) -> dict[str, Any]:
    failures = [c for c in checks if not c.ok]
    return {
        "checked_at": datetime.now(tz=UTC).isoformat(),
        "runner": runner,
        "ok": len(failures) == 0,
        "failure_count": len(failures),
        "checks": [asdict(c) for c in checks],
    }


def save_report(settings: Settings, report: dict[str, Any]) -> None:
    try:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        client.set(REDIS_STATE_KEY, json.dumps(report), ex=60 * 60 * 48)
    except Exception:
        logger.exception("site_watchdog: could not persist state to redis")


def load_last_report(settings: Settings) -> dict[str, Any] | None:
    try:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        raw = client.get(REDIS_STATE_KEY)
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        logger.exception("site_watchdog: could not load state from redis")
        return None


def merge_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for rep in reports:
        checks.extend(rep.get("checks") or [])
    failures = [c for c in checks if not c.get("ok")]
    return {
        "checked_at": datetime.now(tz=UTC).isoformat(),
        "runner": "merged",
        "ok": len(failures) == 0,
        "failure_count": len(failures),
        "checks": checks,
    }


def watchdog_slack_channel(settings: Settings) -> str:
    for attr in ("site_watchdog_slack_channel_id", "slack_agent_discussion_channel_id", "slack_digest_channel_id"):
        val = (getattr(settings, attr, None) or "").strip()
        if val:
            return val
    return ""


def build_slack_text(report: dict[str, Any], *, recovered: bool = False) -> str:
    checked = report.get("checked_at", "?")
    runner = report.get("runner", "?")
    if report.get("ok"):
        if recovered:
            return (
                ":white_check_mark: *Site watchdog — recovered*\n"
                f"Checked {checked} ({runner})\n"
                "Website and server checks are green again."
            )
        return (
            ":white_check_mark: *Site watchdog — all clear*\n"
            f"Checked {checked} ({runner})\n"
            "API, database, Redis, operator UI, and queue depth look healthy."
        )

    lines = [
        ":rotating_light: *Site watchdog — problems detected*",
        f"Checked {checked} ({runner})",
        "",
    ]
    for item in (report.get("checks") or []):
        if item.get("ok"):
            continue
        lines.append(f"• *{item.get('name', '?')}* [{item.get('source', '?')}]: {item.get('detail', '?')}")
    lines.append("")
    lines.append("_Pipeline Slack digest is separate — this agent only checks site + server health._")
    return "\n".join(lines)[:3900]


def should_post_slack(
    settings: Settings,
    report: dict[str, Any],
    previous: dict[str, Any] | None,
) -> tuple[bool, bool]:
    """Return (post, recovered)."""
    now_ok = bool(report.get("ok"))
    prev_ok = previous.get("ok") if previous else None

    if not now_ok:
        return True, False

    if prev_ok is False and now_ok:
        return True, True

    hours = settings.site_watchdog_heartbeat_hours
    if hours > 0 and now_ok and (prev_ok is None or prev_ok is True):
        try:
            prev_at = previous.get("checked_at") if previous else None
            if prev_at:
                prev_dt = datetime.fromisoformat(prev_at.replace("Z", "+00:00"))
                if (datetime.now(tz=UTC) - prev_dt).total_seconds() < hours * 3600:
                    return False, False
        except (TypeError, ValueError):
            pass
        return True, False

    return False, False


def run_droplet_watchdog(db: Session) -> dict[str, Any]:
    settings = get_settings()
    checks = run_public_http_checks(settings, source="droplet")
    checks.extend(run_server_checks(db, settings, source="droplet"))
    report = build_report(checks, runner="celery-droplet")
    save_report(settings, report)
    return report
