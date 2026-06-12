"""Backlog size, value, and rough time-to-finish estimates for operators."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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
BACKLOG_DEPENDENCY_TIMEOUT_SEC = 1.0
SCORE_GAP_BASIS = "identification_plus_pipeline_funnel"
_SCORE_GAPS_YELLOW = 20_000  # aligned with load_governor.py

# Operator-facing server load hints (see load_governor.py and celery_app beat_schedule).
_WORK_TYPE_SERVER_LOAD: dict[str, tuple[str, str]] = {
    "pipeline": (
        "high",
        "Full Atlas/Beacon pipelines — LLM calls plus Postgres; stacks when the parking queue grows.",
    ),
    "scoring": (
        "high",
        "Candidate scoring batches — heavy Postgres only when prescreen-qualified rows still need Atlas/Beacon.",
    ),
    "scoring_signal": (
        "medium",
        "Demand-distance refresh — moderate Postgres; cheaper than full pipeline.",
    ),
    "data_backfill": (
        "medium",
        "External GIS/API lookups (Baltimore Real Property, WA assessor); bounded batches.",
    ),
    "enrichment": (
        "medium",
        "POI / third-party enrichment APIs; throttled to candidate parcels when auto-fix runs.",
    ),
    "deep_enrichment": (
        "high",
        "Owner outreach briefs — expensive LLM + enrichment per top-score parcel.",
    ),
}

_SIGNAL_LABELS: dict[str, str] = {
    "celery_workers_down": "Celery workers offline — queued work cannot drain.",
    "parking_queue_critical": "Parking queue very deep — workers saturated.",
    "parking_queue_high": "Parking queue elevated — scoring/pipeline stacking.",
    "parking_queue_elevated": "Parking queue above normal.",
    "site_watchdog_failed": "Site watchdog failing — public API or bridge may be stressed.",
    "score_gaps_high": "Large actionable scoring gap — scheduled scoring will hammer Postgres.",
    "score_gaps_elevated": "Elevated actionable scoring gap — watch Postgres CPU when Beat tasks fire.",
    "pipeline_funnel_backlog_high": "Large qualified pipeline funnel — enqueue will add worker load.",
    "pipeline_funnel_backlog_elevated": "Qualified pipeline funnel above normal.",
}


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


def _gap_count(export: dict[str, Any], key: str) -> int:
    raw = export.get(key) or {}
    return int(raw.get("count") or 0) if isinstance(raw, dict) else 0


def _candidate_count(export: dict[str, Any], fallback: int = 0) -> int:
    """Address/owner enrichment is only required for deal candidates, not every APN."""
    candidates = _gap_count(export, "parcels_prescreen_qualified")
    return candidates if candidates > 0 else max(0, int(fallback or 0))


def _candidate_owner_brief_missing(export: dict[str, Any], candidate_total: int) -> int:
    """Return the targeted owner brief gap, tolerating older cached snapshots."""
    target_gap = export.get("parcels_missing_owner_outreach_brief")
    if isinstance(target_gap, dict) and "target_count" in target_gap:
        target_total = int(target_gap.get("target_count") or 0)
        return min(_gap_count(export, "parcels_missing_owner_outreach_brief"), target_total or candidate_total)
    scoped = export.get("parcels_prescreen_qualified_missing_owner_outreach_brief")
    if isinstance(scoped, dict):
        return min(_gap_count(export, "parcels_prescreen_qualified_missing_owner_outreach_brief"), candidate_total)
    # Older ops snapshots only have the citywide owner-brief gap. Cap it to the
    # candidate pool so the operator page never presents failed-prescreen parcels
    # as actionable outreach backlog.
    return min(_gap_count(export, "parcels_missing_owner_outreach_brief"), candidate_total)


def _candidate_address_missing(export: dict[str, Any], candidate_total: int) -> tuple[int, int, bool]:
    """Return actionable candidate street-address gap, tolerating older cached snapshots.

    Returns (missing, total, snapshot_stale). When the ops snapshot predates the
    address-gap metric we must not assume every prescreen-qualified parcel lacks
    a street address — that inflated the backlog to 100% of the candidate pool.
    """
    scoped = export.get("parcels_missing_baltimore_candidate_street_address")
    if isinstance(scoped, dict):
        target_total = int(scoped.get("target_count") or candidate_total or 0)
        missing = min(int(scoped.get("count") or 0), target_total or candidate_total)
        return missing, target_total or candidate_total, False
    return 0, candidate_total, True


def _wa_candidate_address_missing(export: dict[str, Any]) -> tuple[int, int]:
    """Washington (53xxx) candidate street-address gaps from export-readiness."""
    scoped = export.get("parcels_missing_wa_candidate_street_address")
    if not isinstance(scoped, dict):
        return 0, 0
    missing = int(scoped.get("count") or 0)
    total = int(scoped.get("target_count") or missing)
    return missing, total


def _optional_int(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _server_load_for_work_type(work_type: str) -> tuple[str, str]:
    return _WORK_TYPE_SERVER_LOAD.get(work_type, ("low", "Background maintenance."))


def _humanize_signal(signal: dict[str, Any]) -> str:
    code = str(signal.get("code") or "")
    base = _SIGNAL_LABELS.get(code, code.replace("_", " "))
    if "depth" in signal:
        return f"{base} (depth={signal['depth']})"
    if "count" in signal:
        return f"{base} (count={signal['count']:,})"
    if signal.get("detail"):
        return f"{base} — {signal['detail']}"
    return base


def _cron_utc(minute: int | str, hour: int | str) -> str:
    return f"{minute} {hour} * * *"


def _setting(settings: Settings, name: str, default: Any) -> Any:
    return getattr(settings, name, default)


def _scheduled_server_jobs(settings: Settings, governor: dict[str, Any]) -> list[dict[str, Any]]:
    """Celery Beat + GitHub agents that can consume Droplet CPU/Postgres."""
    pipe_mult = float(governor.get("pipeline_enqueue_multiplier") or 1.0)
    wa_allowed = bool(governor.get("wa_rollout_allowed", True))
    autofix = bool(governor.get("ops_autofix_allowed", True))
    jobs: list[dict[str, Any]] = []

    def _job(
        name: str,
        schedule_utc: str,
        load_tier: str,
        *,
        enabled: bool,
        throttled: bool = False,
        paused: bool = False,
        note: str = "",
    ) -> None:
        if not enabled:
            return
        status = "paused" if paused else ("throttled" if throttled else "active")
        jobs.append(
            {
                "name": name,
                "schedule_utc": schedule_utc,
                "load_tier": load_tier,
                "status": status,
                "note": note,
            }
        )

    _job(
        "Ops remediation loop",
        _cron_utc(
            _setting(settings, "ops_remediation_crontab_minute", 15),
            _setting(settings, "ops_remediation_crontab_hour", "*/2"),
        ),
        "high",
        enabled=bool(_setting(settings, "ops_remediation_enabled", False)),
        throttled=not autofix,
        note="Caches export-readiness gaps; auto-fix enqueues POI/demand batches when allowed.",
    )
    _job(
        "Priority pipeline enqueue",
        _cron_utc(
            _setting(settings, "scheduled_priority_pipeline_crontab_minute", 20),
            _setting(settings, "scheduled_priority_pipeline_crontab_hour", "*/2"),
        ),
        "high",
        enabled=bool(_setting(settings, "scheduled_priority_pipeline_enabled", False)),
        throttled=pipe_mult < 1.0,
        note=(
            f"Limit {_setting(settings, 'scheduled_priority_pipeline_limit', 75)}/tick "
            f"· governor at {int(pipe_mult * 100)}%."
        ),
    )
    _job(
        "Enqueue unscored pipelines",
        _cron_utc(
            _setting(settings, "scheduled_enqueue_unscored_crontab_minute", 25),
            _setting(settings, "scheduled_enqueue_unscored_crontab_hour", "*/4"),
        ),
        "high",
        enabled=bool(_setting(settings, "scheduled_enqueue_unscored_enabled", False)),
        throttled=pipe_mult < 1.0,
        note=f"Up to {_setting(settings, 'scheduled_enqueue_unscored_limit', 150)} parcels/tick for missing scores.",
    )
    _job(
        "Refresh identification scores",
        _cron_utc(
            _setting(settings, "scheduled_refresh_identification_crontab_minute", 10),
            _setting(settings, "scheduled_refresh_identification_crontab_hour", "*/6"),
        ),
        "high",
        enabled=bool(_setting(settings, "scheduled_refresh_identification_enabled", False)),
        note=f"Batch limit {_setting(settings, 'scheduled_refresh_identification_limit', 2000)}.",
    )
    _job(
        "Refresh demand distances",
        _cron_utc(
            _setting(settings, "scheduled_refresh_demand_crontab_minute", 40),
            _setting(settings, "scheduled_refresh_demand_crontab_hour", "*/6"),
        ),
        "medium",
        enabled=bool(_setting(settings, "scheduled_refresh_demand_enabled", False)),
        note=f"Batch limit {_setting(settings, 'scheduled_refresh_demand_limit', 2000)}.",
    )
    _job(
        "WA statewide county rollout",
        _cron_utc(
            _setting(settings, "wa_statewide_rollout_crontab_minute", 0),
            _setting(settings, "wa_statewide_rollout_crontab_hour", 6),
        ),
        "high",
        enabled=bool(_setting(settings, "wa_statewide_rollout_enabled", False)),
        paused=not wa_allowed,
        note="Ingest + post-ingest scoring per county; paused when load governor is orange/red.",
    )
    _job(
        "Address health agent",
        _cron_utc(
            _setting(settings, "address_health_agent_crontab_minute", 10),
            _setting(settings, "address_health_agent_crontab_hour", "*/12"),
        ),
        "medium",
        enabled=bool(_setting(settings, "address_health_agent_enabled", False)),
        note="Catalog rotation + connector checks; also GitHub Actions every 12h.",
    )
    _job(
        "Baltimore address backfill agent",
        "*/15 * * * *",
        "low",
        enabled=True,
        note="GitHub Actions — bounded GIS batches when API ready.",
    )
    _job(
        "Operator admin agent",
        "0 8 * * *",
        "low",
        enabled=True,
        note="GitHub Actions — Playwright scan + Droplet remediate (daily).",
    )
    _job(
        "Site watchdog",
        f"{_setting(settings, 'site_watchdog_crontab_minute', '0')} * * * *",
        "low",
        enabled=bool(_setting(settings, "site_watchdog_enabled", False)),
        note="HTTP health probes; failures raise governor pressure.",
    )
    return jobs


def _signal_trigger_row(signal: dict[str, Any], *, watchdog_report: dict[str, Any] | None) -> dict[str, Any]:
    code = str(signal.get("code") or "")
    label = _SIGNAL_LABELS.get(code, code.replace("_", " "))
    count = signal.get("count") if signal.get("count") is not None else signal.get("depth")
    detail = label
    if code == "site_watchdog_failed" and watchdog_report:
        failures = [c for c in (watchdog_report.get("checks") or []) if not c.get("ok")]
        if failures:
            bits = [f"{c.get('name')}: {str(c.get('detail') or '')[:120]}" for c in failures[:4]]
            detail = "; ".join(bits)
            if len(failures) > 4:
                detail += f" (+{len(failures) - 4} more)"
    elif "depth" in signal:
        detail = f"{label} (queue depth={signal['depth']:,})"
    elif "count" in signal:
        detail = f"{label} ({int(signal['count']):,} records)"
    elif signal.get("detail"):
        detail = f"{label} — {signal['detail']}"
    return {
        "key": code or "unknown_signal",
        "label": label,
        "record_count": int(count) if count is not None else None,
        "unit": "tasks" if "depth" in signal else "records",
        "role": "pressure_trigger",
        "affects_governor": True,
        "detail": detail,
    }


def _latent_gap_row(*, key: str, label: str, record_count: int, unit: str, detail: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "record_count": record_count,
        "unit": unit,
        "role": "latent",
        "affects_governor": False,
        "detail": detail,
    }


def _active_work_row(*, key: str, label: str, record_count: int, unit: str, status: str, detail: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "record_count": record_count,
        "unit": unit,
        "status": status,
        "detail": detail,
    }


def _server_load_section(
    settings: Settings,
    governor: dict[str, Any],
    *,
    parking_depth: int,
    slack_depth: int,
    ident_missing: int,
    ent_missing: int,
    pipeline_funnel_backlog: int,
    poi_citywide_missing: int,
    poi_candidate_missing: int,
    demand_missing: int,
    items: list[dict[str, Any]],
    watchdog_report: dict[str, Any] | None,
) -> dict[str, Any]:
    signals = governor.get("signals") if isinstance(governor.get("signals"), list) else []
    human_signals = [_humanize_signal(s) for s in signals if isinstance(s, dict)]
    score_gaps = (
        int(governor.get("score_gaps") or 0)
        if governor.get("score_gap_basis") == SCORE_GAP_BASIS
        else ident_missing + pipeline_funnel_backlog
    )
    gross_entitlement_gaps = int(governor.get("gross_entitlement_gaps") or ent_missing)
    trigger_codes = {str(s.get("code") or "") for s in signals if isinstance(s, dict)}
    pressure_triggers = [
        _signal_trigger_row(s, watchdog_report=watchdog_report) for s in signals if isinstance(s, dict)
    ]

    active_work: list[dict[str, Any]] = []
    if parking_depth > 0:
        active_work.append(
            _active_work_row(
                key="celery_parking_queue",
                label="Celery parking queue",
                record_count=parking_depth,
                unit="tasks",
                status="queued",
                detail="Pipeline, scoring, and ingest tasks waiting for or using workers.",
            )
        )
    if slack_depth > 0:
        active_work.append(
            _active_work_row(
                key="celery_slack_queue",
                label="Celery Slack queue",
                record_count=slack_depth,
                unit="tasks",
                status="queued",
                detail="Slack digest and notification tasks waiting to send.",
            )
        )
    if pipeline_funnel_backlog > 0:
        active_work.append(
            _active_work_row(
                key="pipeline_funnel",
                label="Qualified pipeline funnel",
                record_count=pipeline_funnel_backlog,
                unit="parcels",
                status="backlog",
                detail="Prescreen-qualified parcels awaiting Atlas/Beacon full pipeline runs.",
            )
        )
    for item in items:
        backlog_count = int(item.get("backlog_count") or 0)
        if backlog_count <= 0:
            continue
        active_work.append(
            _active_work_row(
                key=str(item.get("key") or "work"),
                label=str(item.get("label") or "Backlog work"),
                record_count=backlog_count,
                unit=str(item.get("unit") or "records"),
                status="backlog",
                detail=str(item.get("why") or item.get("recommendation") or ""),
            )
        )

    latent_gaps: list[dict[str, Any]] = []
    score_gap_triggers = {"score_gaps_high", "score_gaps_elevated"}
    if gross_entitlement_gaps > 0 and not trigger_codes.intersection(score_gap_triggers):
        latent_gaps.append(
            _latent_gap_row(
                key="broad_entitlement_coverage",
                label="Broad entitlement coverage gaps",
                record_count=gross_entitlement_gaps,
                unit="parcels",
                detail=(
                    "Informational only — these rows are not auto-scored unless identification prescreen "
                    "passes. Not throttling the governor in this snapshot."
                ),
            )
        )
    if poi_citywide_missing > 0:
        latent_gaps.append(
            _latent_gap_row(
                key="citywide_poi_optional",
                label="Citywide POI density (optional)",
                record_count=poi_citywide_missing,
                unit="parcels",
                detail=(
                    "Optional enrichment — only runs when ops auto-fix enqueues POI batches. "
                    f"Candidate-scoped POI gap: {poi_candidate_missing:,} parcels."
                ),
            )
        )
    if demand_missing > 0 and demand_missing not in {int(i.get("backlog_count") or 0) for i in items}:
        latent_gaps.append(
            _latent_gap_row(
                key="demand_distance",
                label="Demand distance refresh",
                record_count=demand_missing,
                unit="parcels",
                detail="Scheduled scoring signal refresh — cheap Postgres work when Beat tasks run.",
            )
        )
    if ident_missing > 0 and "score_gaps_high" not in trigger_codes and "score_gaps_elevated" not in trigger_codes:
        latent_gaps.append(
            _latent_gap_row(
                key="identification_scores",
                label="Missing identification scores",
                record_count=ident_missing,
                unit="parcels",
                detail="Below governor yellow threshold in this snapshot — not the current throttle trigger.",
            )
        )

    drivers: list[str] = []
    level = str(governor.get("pressure_level") or "green")
    if pressure_triggers:
        drivers.append(
            f"Governor is {level} because: "
            + "; ".join(row["detail"] for row in pressure_triggers[:3])
            + "."
        )
    elif parking_depth > 0:
        drivers.append(
            f"Celery parking queue has {parking_depth:,} tasks running or waiting — workers are busy now."
        )
    elif level != "green":
        drivers.append(f"Governor is {level} but no structured trigger signals were recorded.")
    else:
        drivers.append("No queue backlog and governor pressure is green.")

    if active_work:
        total_active = sum(int(row["record_count"]) for row in active_work)
        drivers.append(
            f"Active or queued work now: {len(active_work)} stream(s), {total_active:,} total units counted above."
        )
    else:
        drivers.append("Nothing is queued or running on Celery right now — workers are idle.")

    if latent_gaps:
        drivers.append(
            "Latent snapshot gaps below are not driving governor pressure in this assessment "
            f"({len(latent_gaps)} informational row(s))."
        )

    throttles: list[str] = []
    if level != "green":
        if governor.get("pipeline_enqueue_multiplier") is not None:
            throttles.append(
                f"Pipeline enqueue capped at {int(float(governor['pipeline_enqueue_multiplier']) * 100)}%."
            )
        if governor.get("wa_rollout_allowed") is False:
            throttles.append("WA county rollout paused.")
        if governor.get("ops_autofix_allowed") is False:
            throttles.append("Ops auto-fix paused (no automatic POI/demand batches).")

    return {
        "pressure_level": level,
        "assessed_at": governor.get("assessed_at"),
        "parking_queue_depth": parking_depth,
        "slack_queue_depth": slack_depth,
        "score_gaps": score_gaps,
        "ident_score_gaps": ident_missing,
        "ent_score_gaps": pipeline_funnel_backlog,
        "gross_entitlement_gaps": gross_entitlement_gaps,
        "primary_drivers": drivers,
        "signals": human_signals,
        "active_work": active_work,
        "pressure_triggers": pressure_triggers,
        "latent_gaps": latent_gaps,
        "scheduled_jobs": _scheduled_server_jobs(settings, governor),
        "throttles": throttles,
    }


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
    load_tier, load_note = _server_load_for_work_type(work_type)
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
        "server_load_tier": load_tier,
        "server_load_note": load_note,
    }


def _inventory_section(
    *,
    settings: Settings,
    export: dict[str, Any],
    report: dict[str, Any],
    parking_depth: int,
    pipeline_backlog: int,
    governor: dict[str, Any],
) -> dict[str, Any]:
    """Gathered / gathering / to-be-gathered counts from the cached ops snapshot."""
    from parking_core.pilot import load_pilot_config

    records_gathered = int(export.get("parcel_row_total") or 0)
    records_gathering = max(0, parking_depth) + max(0, pipeline_backlog)
    scope = report.get("pilot_scope") if isinstance(report.get("pilot_scope"), dict) else {}
    pilot_county_count = int(scope.get("pilot_county_count") or 0)
    counties_gathered = int(scope.get("counties_with_ingested_parcels") or 0)
    region_name = scope.get("region_name") if isinstance(scope.get("region_name"), str) else None
    if pilot_county_count <= 0:
        pilot_config_path = getattr(settings, "pilot_config_path", None)
        if pilot_config_path:
            pilot = load_pilot_config(pilot_config_path)
            pilot_fips = [str(f).strip() for f in (pilot.region.county_fips or []) if str(f).strip()]
            pilot_county_count = len(pilot_fips)
            if not region_name:
                region_name = pilot.region.name
    counties_to_be_gathered = max(0, pilot_county_count - counties_gathered)
    wa_rollout_paused = governor.get("wa_rollout_allowed") is False
    county_breakdown_pending = counties_gathered <= 0 and records_gathered > 0 and not scope
    if records_gathering > 0:
        gathering_note = (
            f"{parking_depth:,} Celery tasks queued/running · "
            f"{pipeline_backlog:,} prescreen-qualified parcels awaiting full pipeline."
        )
    elif wa_rollout_paused:
        gathering_note = (
            "No queued ingest/scoring tasks right now. WA county rollout is paused by the load governor."
        )
    elif county_breakdown_pending:
        gathering_note = (
            "Parcel total is current; county-by-county breakdown refreshes on the next ops snapshot."
        )
    elif counties_to_be_gathered > 0:
        gathering_note = (
            f"No active queue work. {counties_to_be_gathered} configured "
            f"{'county' if counties_to_be_gathered == 1 else 'counties'} still need GIS ingest."
        )
    else:
        gathering_note = "No queued ingest or pipeline tasks; pilot counties are loaded."
    return {
        "region_name": region_name,
        "records_gathered": records_gathered,
        "records_gathering": records_gathering,
        "counties_gathered": counties_gathered,
        "counties_to_be_gathered": counties_to_be_gathered,
        "pilot_county_count": pilot_county_count,
        "parking_queue_depth": parking_depth,
        "pipeline_backlog": pipeline_backlog,
        "wa_rollout_paused": wa_rollout_paused if pilot_county_count > 0 else None,
        "county_breakdown_pending": county_breakdown_pending,
        "gathering_note": gathering_note,
    }


def backlog_eta_summary(db: Session, settings: Settings) -> dict[str, Any]:
    """Decision-oriented backlog summary: value, pace, and rough ETA by workstream."""
    # This endpoint backs an operator page. Avoid live full-table readiness scans here;
    # Postgres CPU alerts are exactly when operators need the page to load. The ops
    # remediation loop already caches the heavy gap snapshot in Redis.
    report = load_last_report(settings, socket_timeout=BACKLOG_DEPENDENCY_TIMEOUT_SEC) or {}
    report_checked_at = report.get("checked_at") if isinstance(report.get("checked_at"), str) else None
    export = report.get("export_readiness") if isinstance(report.get("export_readiness"), dict) else {}
    priorities = report.get("priority_counties") if isinstance(report.get("priority_counties"), dict) else {}
    priority = priorities.get(BALTIMORE_CITY_FIPS) if isinstance(priorities.get(BALTIMORE_CITY_FIPS), dict) else {}
    priority_total = int(priority.get("total") or 0)
    total = int(export.get("parcel_row_total") or priority_total or 0)
    queues = inspect_redis_queues(settings, socket_timeout=BACKLOG_DEPENDENCY_TIMEOUT_SEC)
    workers = inspect_celery_workers(timeout=BACKLOG_DEPENDENCY_TIMEOUT_SEC)
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
    brief_gap = export.get("parcels_missing_owner_outreach_brief")
    brief_target = (
        int(brief_gap.get("target_count") or 0)
        if isinstance(brief_gap, dict)
        else 0
    )
    address_candidate_total = _candidate_count(export, pipeline_backlog)
    address_missing, address_total, address_snapshot_stale = _candidate_address_missing(
        export,
        address_candidate_total,
    )
    wa_address_missing, wa_address_scope = _wa_candidate_address_missing(export)
    brief_missing = _candidate_owner_brief_missing(export, address_candidate_total)
    brief_total = brief_target or address_total
    brief_recommendation = (
        "Do not run for every parcel; only run for parcels above the owner-outreach score floors."
        if brief_target > 0
        else "Queue qualified candidates only; ignore citywide brief gaps on failed-prescreen parcels."
    )
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
                "Ops snapshot is stale — address gap not counted yet. Wait for the nightly ops loop "
                "or POST /internal/ops/run-now, then reload. Do not treat all candidates as missing."
                if address_snapshot_stale and address_total > 0
                else (
                    "Run measured batches for deal candidates only; do not citywide-backfill low-score parcels."
                    if address_missing > 0
                    else "No action needed."
                )
            ),
            why=(
                "Street addresses make parcel review, maps, visits, and owner conversations usable, "
                "but only for Baltimore deal candidates that pass scoring or look vacant/suitable."
            ),
            eta_confidence="unknown",
            active_now=False,
        ),
        _item(
            key="wa_property_addresses",
            label="WA candidate street addresses",
            backlog_count=wa_address_missing,
            total_count=wa_address_scope or wa_address_missing,
            unit="parcels",
            value="high" if wa_address_missing > 0 else "selective",
            work_type="data_backfill",
            recommendation=(
                "Normalize WaTech situs at ingest; add county assessor roll merges per "
                "data/jurisdictions/wa/source_catalog.csv. City address-point fallback "
                "only for qualified parcels — see address_field_maps.yaml."
                if wa_address_missing > 0
                else "No WA candidate address gap measured, or counties not loaded yet."
            ),
            why=(
                "Washington situs sources vary by county and city. Addresses are required "
                "only for deal candidates (maps, skip-trace, outreach) — not every statewide APN."
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
            label="Actionable score gaps",
            backlog_count=ident_missing + pipeline_backlog,
            total_count=total if total else 0,
            unit="candidate rows",
            value="high",
            work_type="scoring",
            assumed_batch_size=2000,
            assumed_batches_per_day=4,
            eta_confidence="medium",
            recommendation="Run promptly if nonzero; these are the score gaps that can change outreach decisions."
            if ident_missing + pipeline_backlog > 0
            else "No action needed.",
            why=(
                "Identification gaps block prescreening; prescreen-qualified parcels without Atlas/Beacon "
                "scores block outreach decisions. Broad entitlement gaps on ruled-out parcels are informational."
            ),
            active_now=active_work,
        ),
        _item(
            key="owner_outreach_briefs",
            label="Owner outreach briefs for top-score lots",
            backlog_count=brief_missing,
            total_count=brief_total,
            unit="parcels",
            value="selective",
            work_type="deep_enrichment",
            recommendation=(
                brief_recommendation
                if brief_missing > 0
                else "No action needed."
            ),
            why="Outreach briefs are valuable for top-scoring deals, but expensive/noisy for broad parcel inventory.",
            eta_confidence="unknown",
            active_now=active_work,
        ),
    ]
    high_value_remaining = sum(int(i["backlog_count"]) for i in items if i["value"] == "high")
    governor: dict[str, Any] = {
        "pressure_level": "green",
        "ops_autofix_allowed": auto_fix,
        "wa_rollout_allowed": True,
        "pipeline_enqueue_multiplier": 1.0,
        "score_gaps": ident_missing + ent_missing,
        "signals": [],
    }
    if getattr(settings, "load_governor_enabled", False):
        from app.load_governor import load_governor_state

        # This page is an operator fallback during load incidents. Do not
        # recompute governor state here, because that performs extra broker/
        # Redis probes and can make the bridge hit its timeout.
        cached_governor = load_governor_state(settings, socket_timeout=BACKLOG_DEPENDENCY_TIMEOUT_SEC)
        if cached_governor and cached_governor.get("score_gap_basis") == SCORE_GAP_BASIS:
            governor = cached_governor
    base_decision = (
        "No active heavy queue. High-value scoring backlog is clear; "
        "next measured work should be candidate-only street address backfill."
        if (
            parking_depth == 0
            and pipeline_backlog == 0
            and demand_missing == 0
            and ident_missing == 0
        )
        else "High-value backlog remains; prefer pipeline/scoring before medium-value enrichment."
    )
    if governor.get("pressure_level") and governor["pressure_level"] != "green":
        gov_signals = governor.get("signals") if isinstance(governor.get("signals"), list) else []
        trigger_codes = {str(s.get("code") or "") for s in gov_signals if isinstance(s, dict)}
        gap_triggers = trigger_codes & {
            "score_gaps_high",
            "score_gaps_elevated",
            "pipeline_funnel_backlog_high",
            "pipeline_funnel_backlog_elevated",
        }
        if "site_watchdog_failed" in trigger_codes and not gap_triggers and parking_depth == 0:
            base_decision = (
                f"{governor.get('decision', '')} "
                "Actionable scoring backlog is clear and the Celery queue is empty — throttles here are "
                "from site health checks, not from parcel gap counts."
            ).strip()
        else:
            base_decision = f"{governor.get('decision', '')} {base_decision}".strip()
    from app.site_watchdog import load_last_report as load_watchdog_report

    watchdog_report = load_watchdog_report(settings)
    server_load = _server_load_section(
        settings,
        governor,
        parking_depth=parking_depth,
        slack_depth=slack_depth,
        ident_missing=ident_missing,
        ent_missing=ent_missing,
        pipeline_funnel_backlog=pipeline_backlog,
        poi_citywide_missing=poi_citywide_missing,
        poi_candidate_missing=poi_missing,
        demand_missing=demand_missing,
        items=items,
        watchdog_report=watchdog_report if isinstance(watchdog_report, dict) else None,
    )
    inventory = _inventory_section(
        settings=settings,
        export=export,
        report=report,
        parking_depth=parking_depth,
        pipeline_backlog=pipeline_backlog,
        governor=governor,
    )
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
            "decision": base_decision,
            "load_governor_pressure_level": governor.get("pressure_level"),
            "load_governor_decision": governor.get("decision"),
            "pipeline_enqueue_multiplier": governor.get("pipeline_enqueue_multiplier"),
            "wa_rollout_allowed": governor.get("wa_rollout_allowed"),
            "ops_autofix_allowed": governor.get("ops_autofix_allowed"),
            "score_gaps_total": server_load["score_gaps"],
        },
        "inventory": inventory,
        "server_load": server_load,
        "items": items,
    }
