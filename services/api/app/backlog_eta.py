"""Backlog size, value, and rough time-to-finish estimates for operators."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.ops_remediation import (
    effective_auto_fix_enabled,
    inspect_celery_workers,
    inspect_redis_queues,
    load_last_report,
)
from app.pipeline_funnel import entitlement_qualified_floor

BALTIMORE_CITY_FIPS = "24510"
POI_SAFE_BATCH_SIZE = 50
POI_SAFE_BATCHES_PER_DAY = 24


def _pct(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * float(count) / float(total), 2)


def _days_from_daily_rate(count: int, daily_rate: float | None) -> float | None:
    if count <= 0:
        return 0.0
    if not daily_rate or daily_rate <= 0:
        return None
    return round(float(count) / daily_rate, 1)


def _eta_label(days: float | None) -> str:
    if days is None:
        return "Measure one batch first"
    if days <= 0:
        return "Done"
    if days < 1:
        return "< 1 day at assumed pace"
    if days < 14:
        return f"~{days:g} days at assumed pace"
    if days < 90:
        return f"~{round(days)} days at assumed pace"
    return f"~{round(days / 30, 1)} months at assumed pace"


def _status(count: int) -> str:
    if count <= 0:
        return "done"
    return "backlog"


def _cheap_count_baltimore(db: Session) -> int:
    """Cheap fallback when no cached ops snapshot exists."""
    return int(
        db.scalar(
            text("select count(*) from parcels where county_fips = :county_fips"),
            {"county_fips": BALTIMORE_CITY_FIPS},
        )
        or 0
    )


def _gap_count(export: dict[str, Any], key: str) -> int:
    raw = export.get(key) or {}
    return int(raw.get("count") or 0) if isinstance(raw, dict) else 0


def _candidate_count(export: dict[str, Any], fallback: int = 0) -> int:
    """Address/owner enrichment is only required for deal candidates, not every APN."""
    candidates = _gap_count(export, "parcels_prescreen_qualified")
    return candidates if candidates > 0 else max(0, int(fallback or 0))


def _optional_int(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _item(
    *,
    key: str,
    label: str,
    backlog_count: int,
    total_count: int,
    unit: str,
    value: str,
    work_type: str,
    recommendation: str,
    why: str,
    assumed_batch_size: int | None = None,
    assumed_batches_per_day: float | None = None,
    eta_confidence: str = "medium",
    active_now: bool = False,
) -> dict[str, Any]:
    daily_rate = (
        float(assumed_batch_size) * float(assumed_batches_per_day)
        if assumed_batch_size and assumed_batches_per_day
        else None
    )
    days = _days_from_daily_rate(backlog_count, daily_rate)
    return {
        "key": key,
        "label": label,
        "status": _status(backlog_count),
        "active_now": active_now,
        "backlog_count": backlog_count,
        "total_count": total_count,
        "backlog_pct": _pct(backlog_count, total_count),
        "unit": unit,
        "value": value,
        "work_type": work_type,
        "assumed_batch_size": assumed_batch_size,
        "assumed_batches_per_day": assumed_batches_per_day,
        "assumed_units_per_day": daily_rate,
        "eta_days": days,
        "eta_label": _eta_label(days),
        "eta_confidence": eta_confidence,
        "recommendation": recommendation,
        "why": why,
    }


def backlog_eta_summary(db: Session, settings: Settings) -> dict[str, Any]:
    """Decision-oriented backlog summary: value, pace, and rough ETA by workstream."""
    # This endpoint backs an operator page. Avoid live full-table readiness scans here;
    # Postgres CPU alerts are exactly when operators need the page to load. The ops
    # remediation loop already caches the heavy gap snapshot in Redis.
    report = load_last_report(settings) or {}
    report_checked_at = report.get("checked_at") if isinstance(report.get("checked_at"), str) else None
    export = report.get("export_readiness") if isinstance(report.get("export_readiness"), dict) else {}
    priorities = report.get("priority_counties") if isinstance(report.get("priority_counties"), dict) else {}
    priority = priorities.get(BALTIMORE_CITY_FIPS) if isinstance(priorities.get(BALTIMORE_CITY_FIPS), dict) else {}
    priority_total = int(priority.get("total") or 0)
    if priority_total <= 0:
        priority_total = _cheap_count_baltimore(db)
    total = int(export.get("parcel_row_total") or priority_total or 0)
    queues = inspect_redis_queues(settings)
    workers = inspect_celery_workers()
    parking_depth = int(queues.get("parking_depth") or 0)
    slack_depth = int(queues.get("slack_depth") or 0)
    active_work = parking_depth > 0

    poi_citywide_missing = int(priority.get("missing_poi") or 0)
    poi_citywide_missing = int(priority.get("missing_poi_all") or poi_citywide_missing)
    poi_candidate_missing = _optional_int(priority.get("candidate_missing_poi"))
    auto_fix = effective_auto_fix_enabled(settings)
    poi_daily = POI_SAFE_BATCHES_PER_DAY if auto_fix else 0

    pipeline_backlog = int(
        priority.get("pipeline_funnel_backlog")
        or _gap_count(export, "parcels_pipeline_funnel_backlog")
        or 0
    )
    demand_missing = int(
        priority.get("missing_demand_m")
        or _gap_count(export, "parcels_missing_distance_to_nearest_demand_m")
        or 0
    )
    ident_missing = int(
        priority.get("missing_identification_score")
        or _gap_count(export, "parcels_missing_score_identification")
        or 0
    )
    ent_missing = int(
        priority.get("missing_entitlement_score")
        or _gap_count(export, "parcels_missing_score_entitlement")
        or 0
    )
    brief_missing = _gap_count(export, "parcels_missing_owner_outreach_brief")
    address_total = _candidate_count(export, pipeline_backlog)
    poi_candidate_export = export.get("parcels_missing_poi_commercial_count_400m")
    poi_candidate_total_export = export.get("parcels_poi_density_candidates")
    export_has_candidate_mode = (
        isinstance(poi_candidate_export, dict)
        and isinstance(poi_candidate_total_export, dict)
        and (
            bool(poi_candidate_export.get("candidate_mode"))
            or bool(poi_candidate_total_export.get("candidate_mode"))
        )
    )
    if poi_candidate_missing is None and priority.get("poi_candidate_mode"):
        poi_candidate_missing = _optional_int(priority.get("missing_poi"))
    if poi_candidate_missing is None and export_has_candidate_mode:
        poi_candidate_missing = _gap_count(export, "parcels_missing_poi_commercial_count_400m")
    # Older ops snapshots only contain the citywide optional POI gap. Do not present
    # that as actionable backlog on the operator decision page.
    poi_missing = max(0, int(poi_candidate_missing or 0))
    poi_total = int(
        (priority.get("poi_candidate_total") or 0)
        or (_gap_count(export, "parcels_poi_density_candidates") if export_has_candidate_mode else 0)
        or address_total
        or priority_total
    )
    poi_recommendation = (
        "Run only for candidate parcels if revenue confidence is needed; ignore citywide optional gaps."
        if poi_missing > 0
        else "No action needed; citywide POI coverage is optional."
    )
    if auto_fix and poi_missing > 0:
        poi_recommendation = "Throttle to candidate parcels; do not citywide-fill optional POI density."
    # Address jobs should select from this candidate pool only. Avoid scanning
    # raw_properties here so the operator page stays cheap under DB load.
    address_missing = address_total

    items = [
        _item(
            key="baltimore_property_addresses",
            label="Candidate street address backfill",
            backlog_count=address_missing,
            total_count=address_total,
            unit="parcels",
            value="high",
            work_type="data_backfill",
            recommendation=(
                "Run measured batches for deal candidates only; do not citywide-backfill low-score parcels."
                if address_missing > 0
                else "No action needed."
            ),
            why=(
                "Street addresses make parcel review, maps, visits, and owner conversations usable, "
                "but only for parcels that pass scoring or look vacant/suitable."
            ),
            eta_confidence="unknown",
            active_now=False,
        ),
        _item(
            key="baltimore_poi_density",
            label="Candidate POI density",
            backlog_count=poi_missing,
            total_count=poi_total,
            unit="parcels",
            value="medium",
            work_type="enrichment",
            assumed_batch_size=POI_SAFE_BATCH_SIZE,
            assumed_batches_per_day=poi_daily,
            eta_confidence="low",
            recommendation=poi_recommendation,
            why=(
                "POI density improves revenue assumptions for deal candidates only; "
                f"citywide optional gap is {poi_citywide_missing:,} parcels and is not backlog."
            ),
            active_now=active_work,
        ),
        _item(
            key="pipeline_funnel",
            label="Qualified full-pipeline backlog",
            backlog_count=pipeline_backlog,
            total_count=total,
            unit="parcels",
            value="high",
            work_type="pipeline",
            assumed_batch_size=75,
            assumed_batches_per_day=12,
            eta_confidence="medium",
            recommendation="Keep enabled when nonzero; this is the highest-value queue."
            if pipeline_backlog > 0
            else "No action needed.",
            why=(
                "These are prescreen-qualified parcels that should get Atlas/Beacon/deal enrichment. "
                f"Entitlement floor is {entitlement_qualified_floor():.0f}."
            ),
            active_now=active_work,
        ),
        _item(
            key="demand_distance",
            label="Demand distance refresh",
            backlog_count=demand_missing,
            total_count=total,
            unit="parcels",
            value="high",
            work_type="scoring_signal",
            assumed_batch_size=2000,
            assumed_batches_per_day=4,
            eta_confidence="medium",
            recommendation="Run promptly if nonzero; this is cheap and directly affects scoring."
            if demand_missing > 0
            else "No action needed.",
            why="Distance to demand generators is a core parking-demand signal.",
            active_now=active_work,
        ),
        _item(
            key="score_gaps",
            label="Score gaps",
            backlog_count=ident_missing + ent_missing,
            total_count=total * 2 if total else 0,
            unit="score rows",
            value="high",
            work_type="scoring",
            assumed_batch_size=2000,
            assumed_batches_per_day=4,
            eta_confidence="medium",
            recommendation="Run promptly if nonzero; missing scores block decisions."
            if ident_missing + ent_missing > 0
            else "No action needed.",
            why="Identification and entitlement scores decide what enters outreach.",
            active_now=active_work,
        ),
        _item(
            key="owner_outreach_briefs",
            label="Owner outreach briefs",
            backlog_count=brief_missing,
            total_count=total,
            unit="parcels",
            value="selective",
            work_type="deep_enrichment",
            recommendation=(
                "Do not run for every parcel; only run for qualified/high-score/vacant-looking candidates."
                if brief_missing > 0
                else "No action needed."
            ),
            why="Outreach briefs are valuable for deals, but expensive/noisy for parcels that fail prescreen.",
            eta_confidence="unknown",
            active_now=active_work,
        ),
    ]
    high_value_remaining = sum(int(i["backlog_count"]) for i in items if i["value"] == "high")
    return {
        "generated_at": datetime.now(UTC),
        "summary": {
            "active_parking_queue_depth": parking_depth,
            "active_slack_queue_depth": slack_depth,
            "workers_online": bool(workers.get("ok")),
            "worker_detail": workers.get("detail"),
            "ops_auto_fix_enabled": auto_fix,
            "data_checked_at": report_checked_at,
            "data_source": "ops_remediation_snapshot" if report else "live_fallback",
            "high_value_remaining": high_value_remaining,
            "decision": (
                "No active heavy queue. High-value scoring backlog is clear; "
                "next measured work should be candidate-only street address backfill."
                if (
                    parking_depth == 0
                    and pipeline_backlog == 0
                    and demand_missing == 0
                    and ident_missing == 0
                    and ent_missing == 0
                )
                else "High-value backlog remains; prefer pipeline/scoring before medium-value enrichment."
            ),
        },
        "items": items,
    }
