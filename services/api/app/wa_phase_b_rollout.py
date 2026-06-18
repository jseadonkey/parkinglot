"""Capacity-gated WA Phase B (zoning overlay merge) scheduler."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Parcel
from app.wa_statewide_rollout import (
    county_priority_list,
    parcel_counts_by_county,
)
from app.wa_zoning_followup import BLOCKED_ZONING_STATUSES, build_zoning_followup_summary


def load_phase_b_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def county_phase_b_settings(config: dict[str, Any], county_fips: str) -> dict[str, Any]:
    block = (config.get("counties") or {}).get(str(county_fips).strip())
    return dict(block) if isinstance(block, dict) else {}


def county_missing_zoning_stats(db: Session, county_fips: str) -> dict[str, int]:
    total = int(
        db.scalar(select(func.count()).select_from(Parcel).where(Parcel.county_fips == county_fips)) or 0,
    )
    missing = int(
        db.scalar(
            select(func.count())
            .select_from(Parcel)
            .where(Parcel.county_fips == county_fips, Parcel.zoning_code.is_(None)),
        )
        or 0,
    )
    return {"total": total, "missing_zoning": missing}


def _latest_audit(db: Session, action: str) -> AuditLog | None:
    return db.execute(
        select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at.desc()).limit(1),
    ).scalar_one_or_none()


def wa_phase_b_cooldown_state(db: Session, config: dict[str, Any]) -> dict[str, Any]:
    min_hours = float(config.get("min_hours_between_county_merges") or 6.0)
    last = _latest_audit(db, "wa_phase_b_county_merge_completed")
    if last is None or last.created_at is None:
        return {
            "ready": True,
            "required_cooldown_hours": min_hours,
            "hours_since_last_merge": None,
            "last_county_fips": None,
        }
    county = str(last.entity_id or "").strip() or None
    created = last.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age_hours = (datetime.now(UTC) - created).total_seconds() / 3600.0
    return {
        "ready": age_hours >= min_hours,
        "required_cooldown_hours": min_hours,
        "hours_since_last_merge": round(age_hours, 2),
        "last_county_fips": county,
    }


def wa_phase_b_pending_merge_state(db: Session, config: dict[str, Any]) -> dict[str, Any]:
    lock_hours = float(config.get("pending_merge_lock_hours") or 12.0)
    started = _latest_audit(db, "wa_phase_b_county_merge_started")
    completed = _latest_audit(db, "wa_phase_b_county_merge_completed")
    if started is None or started.created_at is None:
        return {
            "pending": False,
            "pending_county_fips": None,
            "pending_age_hours": None,
            "pending_lock_hours": lock_hours,
        }
    if completed is not None and completed.created_at is not None:
        s = started.created_at
        c = completed.created_at
        if s.tzinfo is None:
            s = s.replace(tzinfo=UTC)
        if c.tzinfo is None:
            c = c.replace(tzinfo=UTC)
        if c >= s:
            return {
                "pending": False,
                "pending_county_fips": None,
                "pending_age_hours": None,
                "pending_lock_hours": lock_hours,
            }

    county = str(started.entity_id or "").strip()
    created = started.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age_hours = (datetime.now(UTC) - created).total_seconds() / 3600.0
    pending = bool(county) and age_hours < lock_hours
    return {
        "pending": pending,
        "pending_county_fips": county if pending else None,
        "pending_age_hours": round(age_hours, 2) if pending else None,
        "pending_lock_hours": lock_hours,
    }


def county_ready_for_phase_b(
    db: Session,
    *,
    county_fips: str,
    config: dict[str, Any],
    followup_row: dict[str, Any],
) -> tuple[bool, str]:
    if not followup_row.get("needs_followup"):
        return False, "zoning_trusted_or_no_parcels"
    if followup_row.get("zoning_status") == "blocked":
        return False, "zoning_blocked"
    jurisdiction_counts = followup_row.get("jurisdiction_status_counts") or {}
    if isinstance(jurisdiction_counts, dict) and jurisdiction_counts.keys() <= BLOCKED_ZONING_STATUSES:
        return False, "all_jurisdictions_blocked"

    settings = county_phase_b_settings(config, county_fips)
    overlay_path = str(settings.get("overlay_path") or "").strip()
    auto_build = bool(settings.get("auto_build_overlay"))
    if not auto_build and not (overlay_path and Path(overlay_path).is_file()):
        return False, "no_overlay_builder_or_staged_file"

    stats = county_missing_zoning_stats(db, county_fips)
    total = stats["total"]
    missing = stats["missing_zoning"]
    if total <= 0:
        return False, "no_parcels"
    min_pct = float(config.get("min_missing_zoning_pct") or 1.0)
    missing_pct = 100.0 * float(missing) / float(total)
    if missing_pct < min_pct:
        return False, "zoning_mostly_present"
    return True, "ready"


def next_county_for_phase_b(
    db: Session,
    *,
    config: dict[str, Any],
    pilot_config_path: str,
    parcel_rollout_config: dict[str, Any] | None = None,
) -> str | None:
    """First priority county with parcels, zoning follow-up, and overlay builder/file."""
    rollout = parcel_rollout_config or {}
    priority = county_priority_list(config, pilot_config_path=pilot_config_path)
    if not priority and rollout:
        priority = county_priority_list(rollout, pilot_config_path=pilot_config_path)
    counts = parcel_counts_by_county(db, priority)
    summary = build_zoning_followup_summary(
        parcel_counts=counts,
        priority_order=priority,
    )
    by_fips = {row["county_fips"]: row for row in summary.get("counties") or []}
    for fips in priority:
        row = by_fips.get(fips)
        if not row:
            continue
        ok, _reason = county_ready_for_phase_b(db, county_fips=fips, config=config, followup_row=row)
        if ok:
            return fips
    return None


def phase_b_status_summary(
    db: Session,
    *,
    config: dict[str, Any],
    pilot_config_path: str,
    parcel_rollout_config: dict[str, Any],
    rollout_enabled: bool,
) -> dict[str, Any]:
    priority = county_priority_list(config, pilot_config_path=pilot_config_path)
    if not priority:
        priority = county_priority_list(parcel_rollout_config, pilot_config_path=pilot_config_path)
    counts = parcel_counts_by_county(db, priority)
    summary = build_zoning_followup_summary(
        parcel_counts=counts,
        priority_order=priority,
    )
    next_fips = next_county_for_phase_b(
        db,
        config=config,
        pilot_config_path=pilot_config_path,
        parcel_rollout_config=parcel_rollout_config,
    )
    cooldown = wa_phase_b_cooldown_state(db, config)
    pending = wa_phase_b_pending_merge_state(db, config)
    candidates = []
    for row in summary.get("counties") or []:
        fips = row.get("county_fips")
        if not fips:
            continue
        ok, reason = county_ready_for_phase_b(
            db,
            county_fips=str(fips),
            config=config,
            followup_row=row,
        )
        stats = county_missing_zoning_stats(db, str(fips))
        candidates.append(
            {
                "county_fips": fips,
                "ready": ok,
                "skip_reason": reason,
                "parcels_in_db": stats["total"],
                "parcels_missing_zoning": stats["missing_zoning"],
                "zoning_status": row.get("zoning_status"),
            },
        )
    return {
        "rollout_enabled": rollout_enabled,
        "next_county_fips": next_fips,
        "cooldown_ready": cooldown.get("ready"),
        "required_cooldown_hours": cooldown.get("required_cooldown_hours"),
        "hours_since_last_merge": cooldown.get("hours_since_last_merge"),
        "last_merged_county_fips": cooldown.get("last_county_fips"),
        "pending_merge_county_fips": pending.get("pending_county_fips"),
        "pending_merge_age_hours": pending.get("pending_age_hours"),
        "pending_merge_lock_hours": pending.get("pending_lock_hours"),
        "counties": candidates,
        "zoning_followup": summary,
    }
