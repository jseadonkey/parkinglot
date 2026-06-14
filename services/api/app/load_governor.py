"""Feedback loop: detect downstream load pressure and scale back enqueue / rollout / auto-fix.

Ingest bursts are short; scoring, POI refresh, and pipeline enqueue peg the server when they
stack (see docs/DO-CAPACITY-REVIEW.md). This module reads cheap signals + cached ops snapshots
and exposes effective limits for Beat tasks.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal

import redis
from sqlalchemy.orm import Session

from app.config import Settings
from app.geo_markets import wa_rollout_pacing
from app.ops_remediation import (
    inspect_celery_workers,
    inspect_redis_queues,
    load_last_report,
)
from app.site_watchdog import load_last_report as load_watchdog_report

logger = logging.getLogger(__name__)

REDIS_STATE_KEY = "load_governor:state"
STATE_TTL_SEC = 60 * 45
SCORE_GAP_BASIS = "identification_plus_pipeline_funnel"
_WATCHDOG_PRESSURE_CHECKS = {
    "api_health",
    "api_ready",
    "postgres",
    "redis",
    "celery_parking_queue",
}

PressureLevel = Literal["green", "yellow", "orange", "red"]

# Parking queue depth tiers (tasks waiting — not ingest itself).
_QUEUE_YELLOW = 100
_QUEUE_ORANGE = 500
_QUEUE_RED = 2_000

# Cached export-readiness gaps (downstream work waiting in Postgres).
_SCORE_GAPS_YELLOW = 20_000
_SCORE_GAPS_ORANGE = 50_000
_FUNNEL_YELLOW = 1_000
_FUNNEL_ORANGE = 5_000


def _redis_client(settings: Settings, *, socket_timeout: float | None = None) -> redis.Redis:
    kwargs: dict[str, Any] = {"decode_responses": True}
    if socket_timeout is not None:
        kwargs["socket_connect_timeout"] = socket_timeout
        kwargs["socket_timeout"] = socket_timeout
    return redis.from_url(settings.redis_url, **kwargs)


def _severity_rank(level: PressureLevel) -> int:
    return {"green": 0, "yellow": 1, "orange": 2, "red": 3}[level]


def _max_level(*levels: PressureLevel) -> PressureLevel:
    return max(levels, key=_severity_rank)


def _gap_count(export: dict[str, Any], key: str) -> int:
    raw = export.get(key) or {}
    return int(raw.get("count") or 0) if isinstance(raw, dict) else 0


def _watchdog_pressure_failures(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not report or report.get("ok"):
        return []
    failures = [c for c in (report.get("checks") or []) if isinstance(c, dict) and not c.get("ok")]
    return [c for c in failures if str(c.get("name") or "") in _WATCHDOG_PRESSURE_CHECKS]


def _caps_for_level(level: PressureLevel) -> dict[str, Any]:
    table: dict[PressureLevel, dict[str, Any]] = {
        "green": {
            "pipeline_multiplier": 1.0,
            "wa_rollout_allowed": True,
            "max_auto_pipeline_multiplier": 1.0,
            "ops_autofix_allowed": True,
            "min_days_multiplier": 1.0,
        },
        "yellow": {
            "pipeline_multiplier": 0.5,
            "wa_rollout_allowed": True,
            "max_auto_pipeline_multiplier": 0.75,
            "ops_autofix_allowed": True,
            "min_days_multiplier": 1.5,
        },
        "orange": {
            "pipeline_multiplier": 0.25,
            "wa_rollout_allowed": False,
            "max_auto_pipeline_multiplier": 0.5,
            "ops_autofix_allowed": False,
            "min_days_multiplier": 2.0,
        },
        "red": {
            "pipeline_multiplier": 0.0,
            "wa_rollout_allowed": False,
            "max_auto_pipeline_multiplier": 0.0,
            "ops_autofix_allowed": False,
            "min_days_multiplier": 3.0,
        },
    }
    return table[level]


def assess_load_pressure(
    settings: Settings,
    *,
    cached_ops_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score pressure from queue depth, workers, watchdog, and cached gap snapshot."""
    queues = inspect_redis_queues(settings)
    workers = inspect_celery_workers()
    wd = load_watchdog_report(settings)
    parking = int(queues.get("parking_depth") or 0)

    signals: list[dict[str, Any]] = []
    level: PressureLevel = "green"

    if not workers.get("ok"):
        level = _max_level(level, "red")
        signals.append({"code": "celery_workers_down", "detail": workers.get("detail")})
    elif parking >= _QUEUE_RED:
        level = _max_level(level, "red")
        signals.append({"code": "parking_queue_critical", "depth": parking})
    elif parking >= _QUEUE_ORANGE:
        level = _max_level(level, "orange")
        signals.append({"code": "parking_queue_high", "depth": parking})
    elif parking >= _QUEUE_YELLOW:
        level = _max_level(level, "yellow")
        signals.append({"code": "parking_queue_elevated", "depth": parking})

    wd_pressure = _watchdog_pressure_failures(wd)
    if wd_pressure:
        level = _max_level(level, "orange")
        signals.append(
            {
                "code": "site_watchdog_failed",
                "failures": [str(c.get("name") or "?") for c in wd_pressure[:6]],
            },
        )

    report = cached_ops_report if cached_ops_report is not None else load_last_report(settings)
    export = (report or {}).get("export_readiness") if isinstance(report, dict) else None
    score_gaps = 0
    gross_entitlement_gaps = 0
    funnel_backlog = 0
    if isinstance(export, dict):
        # Identification gaps block prescreening. Entitlement gaps only create
        # actionable scoring work after a parcel passes identification prescreen;
        # otherwise they are broad coverage gaps and should not throttle ingest.
        gross_entitlement_gaps = _gap_count(export, "parcels_missing_score_entitlement")
        funnel_backlog = _gap_count(export, "parcels_pipeline_funnel_backlog")
        score_gaps = _gap_count(export, "parcels_missing_score_identification") + funnel_backlog
        if score_gaps >= _SCORE_GAPS_ORANGE:
            level = _max_level(level, "orange")
            signals.append({"code": "score_gaps_high", "count": score_gaps})
        elif score_gaps >= _SCORE_GAPS_YELLOW:
            level = _max_level(level, "yellow")
            signals.append({"code": "score_gaps_elevated", "count": score_gaps})
        if funnel_backlog >= _FUNNEL_ORANGE:
            level = _max_level(level, "orange")
            signals.append({"code": "pipeline_funnel_backlog_high", "count": funnel_backlog})
        elif funnel_backlog >= _FUNNEL_YELLOW:
            level = _max_level(level, "yellow")
            signals.append({"code": "pipeline_funnel_backlog_elevated", "count": funnel_backlog})

    caps = _caps_for_level(level)
    pacing = wa_rollout_pacing()
    base_min_days = float(pacing.get("min_days_between_counties") or 4)
    base_max_pipe = int(pacing.get("max_auto_pipeline") or 15)

    decision_parts: list[str] = []
    if level == "green":
        decision_parts.append("Load is healthy — scheduled enqueue and rollout may run at full caps.")
    elif level == "yellow":
        decision_parts.append(
            "Moderate downstream pressure — pipeline enqueue and post-ingest work scaled to 50%."
        )
    elif level == "orange":
        decision_parts.append(
            "High downstream pressure — WA county rollout paused; pipeline enqueue cut to 25%; "
            "ops auto-fix paused until gaps drain."
        )
    else:
        decision_parts.append(
            "Critical load — pipeline enqueue paused; defer new county ingest until the parking queue clears."
        )

    return {
        "assessed_at": datetime.now(UTC).isoformat(),
        "pressure_level": level,
        "parking_queue_depth": parking,
        "workers_online": bool(workers.get("ok")),
        "worker_detail": workers.get("detail"),
        "score_gaps": score_gaps,
        "score_gap_basis": SCORE_GAP_BASIS,
        "gross_entitlement_gaps": gross_entitlement_gaps,
        "pipeline_funnel_backlog": funnel_backlog,
        "signals": signals,
        "decision": " ".join(decision_parts),
        "wa_rollout_allowed": bool(caps["wa_rollout_allowed"]),
        "ops_autofix_allowed": bool(caps["ops_autofix_allowed"]),
        "pipeline_enqueue_multiplier": float(caps["pipeline_multiplier"]),
        "max_auto_pipeline_multiplier": float(caps["max_auto_pipeline_multiplier"]),
        "min_days_between_counties_effective": round(
            base_min_days * float(caps["min_days_multiplier"]),
            1,
        ),
        "max_auto_pipeline_effective": max(
            0,
            int(round(base_max_pipe * float(caps["max_auto_pipeline_multiplier"]))),
        ),
    }


def save_governor_state(settings: Settings, state: dict[str, Any]) -> None:
    try:
        _redis_client(settings).set(REDIS_STATE_KEY, json.dumps(state), ex=STATE_TTL_SEC)
    except Exception:
        logger.exception("load_governor: could not persist state")


def load_governor_state(settings: Settings, *, socket_timeout: float | None = None) -> dict[str, Any] | None:
    try:
        raw = _redis_client(settings, socket_timeout=socket_timeout).get(REDIS_STATE_KEY)
        return json.loads(raw) if raw else None
    except Exception:
        logger.exception("load_governor: could not load state")
        return None


def refresh_load_governor(
    settings: Settings,
    *,
    db: Session | None = None,  # noqa: ARG001 — reserved for future DB-backed signals
    cached_ops_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute pressure and persist to Redis."""
    state = assess_load_pressure(settings, cached_ops_report=cached_ops_report)
    save_governor_state(settings, state)
    return state


def current_governor_state(settings: Settings) -> dict[str, Any]:
    """Cached state if fresh; otherwise quick reassess (no DB)."""
    cached = load_governor_state(settings)
    if cached and cached.get("score_gap_basis") == SCORE_GAP_BASIS:
        return cached
    return refresh_load_governor(settings)


def effective_pipeline_limit(requested: int, settings: Settings, state: dict[str, Any] | None = None) -> int:
    """Scale Beat pipeline enqueue cap by current pressure."""
    st = state or current_governor_state(settings)
    mult = float(st.get("pipeline_enqueue_multiplier") or 1.0)
    if mult <= 0:
        return 0
    return max(0, min(int(requested), int(requested * mult)))


def governor_allows_wa_rollout(settings: Settings, state: dict[str, Any] | None = None) -> tuple[bool, str]:
    st = state or current_governor_state(settings)
    if not st.get("wa_rollout_allowed", True):
        return False, st.get("decision") or "load_governor blocked WA rollout"
    return True, ""


def effective_wa_rollout_limits(
    settings: Settings,
    *,
    base_min_days: float,
    base_max_auto_pipeline: int,
    state: dict[str, Any] | None = None,
) -> tuple[float, int]:
    st = state or current_governor_state(settings)
    min_days = max(base_min_days, float(st.get("min_days_between_counties_effective") or base_min_days))
    max_pipe = int(st.get("max_auto_pipeline_effective") or base_max_auto_pipeline)
    return min_days, max(0, min(base_max_auto_pipeline, max_pipe))
