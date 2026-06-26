"""Rollout Orchestrator — supervisor for WA Phase A/B county queue and Baltimore chain."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.baltimore_phase_b import BALTIMORE_CITY_FIPS
from app.config import Settings
from app.wa_phase_b_rollout import (
    celery_task_still_active,
    load_phase_b_config,
    phase_b_merge_lock_holder,
    phase_b_status_summary,
    release_phase_b_merge_lock,
)
from app.wa_statewide_rollout import load_rollout_config, parking_queue_depth

logger = logging.getLogger(__name__)

ORCH_REDIS_STATE_KEY = "rollout_orchestrator:last_summary"


def clear_stale_phase_b_locks(settings: Settings, *, county_fips: str) -> dict[str, Any]:
    """Remove Redis merge lock when the holder task is no longer active."""
    holder = phase_b_merge_lock_holder(settings.redis_url, county_fips)
    if not holder:
        return {"cleared": False, "county_fips": county_fips, "reason": "no_lock"}
    if celery_task_still_active(holder):
        return {
            "cleared": False,
            "county_fips": county_fips,
            "reason": "task_still_active",
            "holder_task_id": holder,
        }
    release_phase_b_merge_lock(settings.redis_url, county_fips, holder)
    logger.info(
        "rollout_orchestrator: cleared stale phase_b lock county=%s holder=%s",
        county_fips,
        holder,
    )
    return {"cleared": True, "county_fips": county_fips, "former_holder": holder}


def rollout_health_snapshot(
    db: Session,
    settings: Settings,
) -> dict[str, Any]:
    phase_b = load_phase_b_config(settings.wa_phase_b_rollout_config_path)
    parcel_rollout = load_rollout_config(settings.wa_statewide_rollout_config_path)
    pb = phase_b_status_summary(
        db,
        config=phase_b,
        pilot_config_path=settings.pilot_config_path,
        parcel_rollout_config=parcel_rollout,
        rollout_enabled=settings.wa_phase_b_rollout_enabled,
        redis_url=settings.redis_url,
    )
    queue = parking_queue_depth(settings.redis_url)
    locks_checked: list[dict[str, Any]] = []
    for row in pb.get("counties") or []:
        fips = str(row.get("county_fips") or "").strip()
        if not fips:
            continue
        holder = phase_b_merge_lock_holder(settings.redis_url, fips)
        if holder:
            locks_checked.append(
                {
                    "county_fips": fips,
                    "holder_task_id": holder,
                    "active": celery_task_still_active(holder),
                },
            )
    return {
        "at": datetime.now(UTC).isoformat(),
        "parking_queue_depth": queue,
        "phase_b": {
            "rollout_enabled": pb.get("rollout_enabled"),
            "next_county_fips": pb.get("next_county_fips"),
            "pending_merge_county_fips": pb.get("pending_merge_county_fips"),
            "pending_merge_age_hours": pb.get("pending_merge_age_hours"),
            "last_merged_county_fips": pb.get("last_merged_county_fips"),
            "hours_since_last_merge": pb.get("hours_since_last_merge"),
        },
        "merge_locks": locks_checked,
        "baltimore_phase_b": _baltimore_chain_state(db, settings),
    }


def _baltimore_chain_state(db: Session, settings: Settings) -> dict[str, Any]:
    from app.baltimore_phase_b import baltimore_needs_phase_b_merge

    needs, stats = baltimore_needs_phase_b_merge(db)
    holder = phase_b_merge_lock_holder(settings.redis_url, BALTIMORE_CITY_FIPS)
    return {
        "needs_merge": needs,
        "merge_lock_holder": holder,
        "merge_lock_active": celery_task_still_active(holder) if holder else False,
        **stats,
    }


def _redis_client(settings: Settings):
    import redis

    return redis.from_url(settings.redis_url)


def _load_last_summary(settings: Settings) -> dict[str, Any] | None:
    try:
        client = _redis_client(settings)
        raw = client.get(ORCH_REDIS_STATE_KEY)
        client.close()
        if not raw:
            return None
        text = raw.decode() if isinstance(raw, bytes) else str(raw)
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        logger.exception("rollout_orchestrator: failed reading last summary")
        return None


def _save_summary(settings: Settings, summary: dict[str, Any]) -> None:
    try:
        client = _redis_client(settings)
        client.set(ORCH_REDIS_STATE_KEY, json.dumps(summary, default=str), ex=86400 * 7)
        client.close()
    except Exception:
        logger.exception("rollout_orchestrator: failed saving summary")


def summary_changed(prev: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if prev is None:
        return True
    keys = (
        ("phase_b", "next_county_fips"),
        ("phase_b", "pending_merge_county_fips"),
        ("phase_b", "last_merged_county_fips"),
    )
    for head, key in keys:
        block_prev = prev.get(head) or {}
        block_cur = current.get(head) or {}
        if block_prev.get(key) != block_cur.get(key):
            return True
    return False


def format_slack_status(summary: dict[str, Any], *, actions: list[str]) -> str:
    pb = summary.get("phase_b") or {}
    lines = [
        "*Rollout Orchestrator*",
        f"• Parking queue depth: *{summary.get('parking_queue_depth')}*",
        f"• Phase B next county: `{pb.get('next_county_fips') or '—'}`",
        f"• Phase B pending merge: `{pb.get('pending_merge_county_fips') or 'none'}`"
        + (
            f" ({pb.get('pending_merge_age_hours')}h)"
            if pb.get("pending_merge_age_hours") is not None
            else ""
        ),
        f"• Last merged: `{pb.get('last_merged_county_fips') or '—'}`"
        + (
            f" ({pb.get('hours_since_last_merge')}h ago)"
            if pb.get("hours_since_last_merge") is not None
            else ""
        ),
    ]
    stale = [lk for lk in summary.get("merge_locks") or [] if not lk.get("active")]
    if stale:
        lines.append(f"• Cleared stale merge locks: *{len(stale)}*")
    bal = summary.get("baltimore_phase_b") or {}
    if bal.get("needs_merge"):
        lines.append(
            f"• Baltimore Phase B: *needs merge* ({bal.get('missing_pct', '?')}% missing)"
        )
    elif bal.get("total"):
        lines.append("• Baltimore Phase B: merge complete or not needed")
    if actions:
        lines.append("• Actions: " + "; ".join(actions))
    return "\n".join(lines)


def run_orchestrator_tick(db: Session, settings: Settings) -> dict[str, Any]:
    """One supervisor pass: recover locks, optionally kick idle Phase B, notify Slack."""
    from app.slack_digest import post_agent_event_to_slack

    actions: list[str] = []
    phase_b = load_phase_b_config(settings.wa_phase_b_rollout_config_path)
    priority = list(phase_b.get("county_fips_priority") or []) + [BALTIMORE_CITY_FIPS]

    for fips in priority:
        result = clear_stale_phase_b_locks(settings, county_fips=str(fips))
        if result.get("cleared"):
            actions.append(f"cleared lock {fips}")

    snapshot = rollout_health_snapshot(db, settings)
    prev = _load_last_summary(settings)

    kick_task_id: str | None = None
    stale_cleared = any(a.startswith("cleared lock") for a in actions)
    if (
        stale_cleared
        and settings.wa_phase_b_rollout_enabled
        and not snapshot["phase_b"].get("pending_merge_county_fips")
        and snapshot.get("parking_queue_depth", 999) <= int(phase_b.get("max_parking_queue_depth") or 300)
        and snapshot["phase_b"].get("next_county_fips")
    ):
        from app.tasks import wa_phase_b_rollout_tick

        ar = wa_phase_b_rollout_tick.delay()
        kick_task_id = ar.id
        actions.append(f"kicked phase_b tick ({ar.id})")

    snapshot["actions"] = actions
    snapshot["kick_task_id"] = kick_task_id
    _save_summary(settings, snapshot)

    if summary_changed(prev, snapshot) or actions:
        post_agent_event_to_slack(
            settings,
            agent="Rollout Orchestrator",
            detail=format_slack_status(snapshot, actions=actions),
        )

    return snapshot
