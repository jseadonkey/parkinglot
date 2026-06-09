"""Ops remediation loop — detect data/worker gaps and enqueue safe fixes.

Runs on a schedule (Celery Beat) and can be triggered manually. Complements site_watchdog
(uptime) with backlog-oriented repairs for the priority market (Baltimore City).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import redis
from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from app.celery_app import celery
from app.config import Settings, get_settings
from app.db.models import Parcel, ParcelScore
from app.db.schema_compat import column_exists
from app.export_readiness import export_readiness_summary
from app.geo_markets import priority_county_fips
from app.pipeline_funnel import (
    identification_prescreen_floor,
    identification_prescreen_qualified,
    pipeline_funnel_backlog,
)
from app.poi_density import POI_DENSITY_CANDIDATE_MODE, count_poi_density_candidates
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION
from app.site_watchdog import load_last_report as load_watchdog_report
from app.site_watchdog import watchdog_slack_channel

logger = logging.getLogger(__name__)

REDIS_STATE_KEY = "ops_remediation:last"
REDIS_COOLDOWN_PREFIX = "ops_remediation:cooldown:"
POI_REFRESH_TASK_NAME = "app.tasks.refresh_poi_density_batch"


def effective_auto_fix_enabled(settings: Settings) -> bool:
    """Fail-safe: auto-fix may diagnose by default, but DB writes need explicit opt-in."""
    return bool(settings.ops_remediation_auto_fix and settings.ops_remediation_allow_db_writes)


@dataclass
class OpsIssue:
    code: str
    severity: str  # critical | warning | info
    message: str
    metric: dict[str, Any] | None = None
    fix_action: str | None = None


@dataclass
class RemediationAction:
    action: str
    status: str  # enqueued | skipped_cooldown | skipped_disabled | failed
    detail: str
    task_id: str | None = None


@dataclass
class QueuedPoiRefreshTask:
    raw: str
    task_id: str | None
    limit: int
    county_fips: str | None
    only_missing: bool
    process_all: bool


def _redis_client(settings: Settings) -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


def save_report(settings: Settings, report: dict[str, Any]) -> None:
    try:
        _redis_client(settings).set(REDIS_STATE_KEY, json.dumps(report), ex=60 * 60 * 72)
    except Exception:
        logger.exception("ops_remediation: could not persist state")


def load_last_report(settings: Settings) -> dict[str, Any] | None:
    try:
        raw = _redis_client(settings).get(REDIS_STATE_KEY)
        return json.loads(raw) if raw else None
    except Exception:
        logger.exception("ops_remediation: could not load state")
        return None


def _cooldown_key(action: str) -> str:
    return f"{REDIS_COOLDOWN_PREFIX}{action}"


def cooldown_active(settings: Settings, action: str) -> bool:
    try:
        return bool(_redis_client(settings).exists(_cooldown_key(action)))
    except Exception:
        return False


def set_cooldown(settings: Settings, action: str, *, seconds: int) -> None:
    try:
        _redis_client(settings).set(_cooldown_key(action), "1", ex=max(60, seconds))
    except Exception:
        logger.exception("ops_remediation: could not set cooldown for %s", action)


def inspect_celery_workers(*, timeout: float = 3.0) -> dict[str, Any]:
    try:
        try:
            with celery.connection_or_acquire() as conn:
                conn.ensure_connection(max_retries=1, timeout=min(timeout, 2.0))
        except Exception as conn_exc:
            return {
                "ok": False,
                "worker_count": 0,
                "detail": f"Broker unreachable: {conn_exc}"[:240],
            }
        insp = celery.control.inspect(timeout=timeout)
        stats = insp.stats() if insp else None
        if not stats:
            return {
                "ok": False,
                "worker_count": 0,
                "detail": "No Celery workers responded (tasks stay PENDING)",
            }
        return {
            "ok": True,
            "worker_count": len(stats),
            "hosts": sorted(stats.keys()),
            "detail": f"{len(stats)} worker(s) online",
        }
    except Exception as exc:
        return {"ok": False, "worker_count": 0, "detail": str(exc)[:240]}


def inspect_redis_queues(settings: Settings) -> dict[str, Any]:
    try:
        client = _redis_client(settings)
        parking_len = int(client.llen("parking") or 0)
        slack_len = int(client.llen("slack") or 0)
        warn = settings.site_watchdog_parking_queue_warn
        return {
            "ok": parking_len < warn,
            "parking_depth": parking_len,
            "slack_depth": slack_len,
            "warn_threshold": warn,
            "detail": f"parking queue={parking_len}, slack={slack_len}",
        }
    except Exception as exc:
        return {"ok": False, "detail": str(exc)[:240]}


def _bool_from_task_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _decode_celery_body(envelope: dict[str, Any]) -> Any:
    body = envelope.get("body")
    if isinstance(body, str):
        try:
            body_bytes = base64.b64decode(body)
        except (binascii.Error, ValueError):
            return None
        encoding = envelope.get("content-encoding") or "utf-8"
        try:
            return json.loads(body_bytes.decode(str(encoding)))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return None
    return body


def _parse_queued_poi_refresh(raw: str) -> QueuedPoiRefreshTask | None:
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(envelope, dict):
        return None

    headers = envelope.get("headers") if isinstance(envelope.get("headers"), dict) else {}
    properties = envelope.get("properties") if isinstance(envelope.get("properties"), dict) else {}
    task_name = headers.get("task")
    task_id = headers.get("id") or properties.get("correlation_id")

    decoded = _decode_celery_body(envelope)
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    if isinstance(decoded, list) and len(decoded) >= 2:
        args = decoded[0] if isinstance(decoded[0], list) else []
        kwargs = decoded[1] if isinstance(decoded[1], dict) else {}
    elif isinstance(decoded, dict):
        task_name = task_name or decoded.get("task")
        task_id = task_id or decoded.get("id")
        raw_args = decoded.get("args")
        raw_kwargs = decoded.get("kwargs")
        args = raw_args if isinstance(raw_args, list) else []
        kwargs = raw_kwargs if isinstance(raw_kwargs, dict) else {}

    if task_name != POI_REFRESH_TASK_NAME:
        return None

    def arg_or_kw(index: int, key: str, default: Any) -> Any:
        if key in kwargs:
            return kwargs[key]
        return args[index] if len(args) > index else default

    limit = arg_or_kw(0, "limit", 50)
    try:
        parsed_limit = min(max(int(limit), 1), 200)
    except (TypeError, ValueError):
        parsed_limit = 50
    county_fips_raw = arg_or_kw(1, "county_fips", None)
    county_fips = str(county_fips_raw).strip() if county_fips_raw is not None else None
    return QueuedPoiRefreshTask(
        raw=raw,
        task_id=str(task_id) if task_id else None,
        limit=parsed_limit,
        county_fips=county_fips or None,
        only_missing=_bool_from_task_value(arg_or_kw(2, "only_missing", True), default=True),
        process_all=_bool_from_task_value(arg_or_kw(3, "process_all", False), default=False),
    )


def _missing_poi_refresh_count(db: Session, county_fips: str | None) -> int:
    if not column_exists(db, "parcels", "poi_commercial_count_400m"):
        return 0
    return count_poi_density_candidates(
        db,
        county_fips=county_fips,
        missing_only=True,
        require_footprint=True,
    )


def _plan_poi_queue_prune(db: Session, messages: list[str]) -> dict[str, Any]:
    kept_messages: list[str] = []
    removals: list[dict[str, Any]] = []
    missing_by_scope: dict[str | None, int] = {}
    covered_capacity: dict[str | None, int] = {}
    process_all_seen: set[str | None] = set()
    parsed = 0

    def missing_count(county_fips: str | None) -> int:
        if county_fips not in missing_by_scope:
            missing_by_scope[county_fips] = _missing_poi_refresh_count(db, county_fips)
        return missing_by_scope[county_fips]

    for raw in messages:
        task = _parse_queued_poi_refresh(raw)
        if task is None:
            kept_messages.append(raw)
            continue
        parsed += 1
        if not task.only_missing:
            kept_messages.append(raw)
            continue

        missing = missing_count(task.county_fips)
        capacity = covered_capacity.get(task.county_fips, 0)
        reason: str | None = None
        if missing <= 0:
            reason = "no_matching_parcels_missing_poi"
        elif task.county_fips in process_all_seen or capacity >= missing:
            reason = "covered_by_earlier_queued_poi_refresh"

        if reason is not None:
            removals.append(
                {
                    "task_id": task.task_id,
                    "county_fips": task.county_fips,
                    "limit": task.limit,
                    "process_all": task.process_all,
                    "missing_poi": missing,
                    "reason": reason,
                },
            )
            continue

        kept_messages.append(raw)
        if task.process_all:
            process_all_seen.add(task.county_fips)
            covered_capacity[task.county_fips] = missing
        else:
            covered_capacity[task.county_fips] = capacity + task.limit

    return {
        "ok": True,
        "scanned": len(messages),
        "poi_refresh_tasks": parsed,
        "removable": len(removals),
        "kept": len(kept_messages),
        "missing_poi_by_scope": {
            ("*" if county_fips is None else county_fips): count
            for county_fips, count in missing_by_scope.items()
        },
        "removals": removals,
        "_kept_messages": kept_messages,
    }


def inspect_poi_refresh_queue(
    db: Session,
    settings: Settings,
    *,
    queue_name: str = "parking",
) -> dict[str, Any]:
    try:
        messages = list(_redis_client(settings).lrange(queue_name, 0, -1) or [])
        plan = _plan_poi_queue_prune(db, messages)
        plan["queue"] = queue_name
        plan.pop("_kept_messages", None)
        return plan
    except Exception as exc:
        return {"ok": False, "queue": queue_name, "detail": str(exc)[:240]}


def prune_queued_poi_refresh_tasks(
    db: Session,
    settings: Settings,
    *,
    queue_name: str = "parking",
    dry_run: bool = False,
) -> dict[str, Any]:
    client = _redis_client(settings)
    removed_task_ids: list[str] = []
    for _attempt in range(3):
        with client.pipeline() as pipe:
            try:
                pipe.watch(queue_name)
                messages = list(pipe.lrange(queue_name, 0, -1) or [])
                plan = _plan_poi_queue_prune(db, messages)
                kept_messages = list(plan.pop("_kept_messages"))
                plan["queue"] = queue_name
                plan["dry_run"] = dry_run
                if dry_run or not plan["removable"]:
                    pipe.unwatch()
                    plan["revoked_task_ids"] = []
                    return plan

                pipe.multi()
                pipe.delete(queue_name)
                if kept_messages:
                    pipe.rpush(queue_name, *kept_messages)
                pipe.execute()
                removed_task_ids = [
                    str(r["task_id"])
                    for r in plan["removals"]
                    if r.get("task_id")
                ]
                break
            except redis.WatchError:
                continue
    else:
        return {
            "ok": False,
            "queue": queue_name,
            "dry_run": dry_run,
            "detail": "Redis queue changed while pruning; retry later",
        }

    if removed_task_ids:
        try:
            celery.control.revoke(removed_task_ids, terminate=False)
        except Exception:
            logger.exception("ops_remediation: could not revoke removed POI refresh tasks")
    plan["revoked_task_ids"] = removed_task_ids
    return plan


def county_data_gaps(db: Session, county_fips: str) -> dict[str, Any]:
    """Gap counts for one county (priority market diagnostics)."""
    cf = county_fips.strip()
    total = int(
        db.scalar(select(func.count()).select_from(Parcel).where(Parcel.county_fips == cf)) or 0,
    )
    if total == 0:
        return {"county_fips": cf, "total": 0}

    no_demand = int(
        db.scalar(
            select(func.count()).select_from(Parcel).where(
                Parcel.county_fips == cf,
                Parcel.distance_to_nearest_demand_m.is_(None),
            ),
        )
        or 0,
    )
    no_poi = 0
    no_poi_all = 0
    poi_candidates = count_poi_density_candidates(db, county_fips=cf, require_footprint=True)
    if column_exists(db, "parcels", "poi_commercial_count_400m"):
        no_poi = count_poi_density_candidates(
            db,
            county_fips=cf,
            missing_only=True,
            require_footprint=True,
        )
        no_poi_all = int(
            db.scalar(
                select(func.count()).select_from(Parcel).where(
                    Parcel.county_fips == cf,
                    Parcel.poi_commercial_count_400m.is_(None),
                ),
            )
            or 0,
        )
    prescreen_floor = identification_prescreen_floor()
    miss_ent = int(
        db.scalar(
            select(func.count())
            .select_from(Parcel)
            .where(
                Parcel.county_fips == cf,
                identification_prescreen_qualified(prescreen_floor),
                ~exists(
                    select(1).where(
                        ParcelScore.parcel_id == Parcel.id,
                        ParcelScore.score_profile == ENTITLEMENT,
                    ),
                ),
            ),
        )
        or 0,
    )
    miss_ident = int(
        db.scalar(
            select(func.count())
            .select_from(Parcel)
            .where(
                Parcel.county_fips == cf,
                ~exists(
                    select(1).where(
                        ParcelScore.parcel_id == Parcel.id,
                        ParcelScore.score_profile == IDENTIFICATION,
                    ),
                ),
            ),
        )
        or 0,
    )
    funnel = int(
        db.scalar(
            select(func.count())
            .select_from(Parcel)
            .where(and_(Parcel.county_fips == cf, pipeline_funnel_backlog(prescreen_floor))),
        )
        or 0,
    )

    return {
        "county_fips": cf,
        "total": total,
        "poi_candidate_total": poi_candidates,
        "poi_candidate_mode": POI_DENSITY_CANDIDATE_MODE,
        "missing_demand_m": no_demand,
        "missing_poi": no_poi,
        "candidate_missing_poi": no_poi,
        "missing_poi_all": no_poi_all,
        "missing_entitlement_score": miss_ent,
        "missing_identification_score": miss_ident,
        "pipeline_funnel_backlog": funnel,
    }


def diagnose(db: Session, settings: Settings) -> list[OpsIssue]:
    issues: list[OpsIssue] = []
    workers = inspect_celery_workers()
    if not workers.get("ok"):
        issues.append(
            OpsIssue(
                code="celery_workers_down",
                severity="critical",
                message=workers.get("detail", "Celery workers unavailable"),
                metric=workers,
                fix_action=None,
            ),
        )

    queues = inspect_redis_queues(settings)
    if not queues.get("ok") and queues.get("parking_depth") is not None:
        issues.append(
            OpsIssue(
                code="parking_queue_high",
                severity="warning",
                message=f"Parking queue depth {queues['parking_depth']} exceeds warn threshold",
                metric=queues,
                fix_action="enqueue_incomplete_limited",
            ),
        )
    if int(queues.get("parking_depth") or 0) > 0:
        poi_queue = inspect_poi_refresh_queue(db, settings)
        if poi_queue.get("ok") and int(poi_queue.get("removable") or 0) > 0:
            issues.append(
                OpsIssue(
                    code="unneeded_poi_refresh_queue",
                    severity="info",
                    message=(
                        f"{poi_queue['removable']} queued POI refresh task(s) are no longer needed"
                    ),
                    metric=poi_queue,
                    fix_action="prune_poi_refresh_queue",
                ),
            )

    wd = load_watchdog_report(settings)
    if wd and not wd.get("ok"):
        failed = [c for c in (wd.get("checks") or []) if not c.get("ok")]
        issues.append(
            OpsIssue(
                code="site_watchdog_failed",
                severity="critical",
                message=f"Last site watchdog reported {len(failed)} failure(s)",
                metric={"failures": [c.get("name") for c in failed[:8]]},
                fix_action="run_site_watchdog",
            ),
        )

    for cf in priority_county_fips():
        gaps = county_data_gaps(db, cf)
        total = int(gaps.get("total") or 0)
        if total <= 0:
            continue
        if int(gaps.get("missing_demand_m") or 0) > 0:
            issues.append(
                OpsIssue(
                    code=f"missing_demand_{cf}",
                    severity="warning",
                    message=f"{gaps['missing_demand_m']} parcels in {cf} missing demand distance",
                    metric=gaps,
                    fix_action="refresh_demand_process_all",
                ),
            )
        if int(gaps.get("missing_entitlement_score") or 0) > 0:
            issues.append(
                OpsIssue(
                    code=f"missing_entitlement_{cf}",
                    severity="warning",
                    message=f"{gaps['missing_entitlement_score']} parcels in {cf} missing entitlement score",
                    metric=gaps,
                    fix_action="refresh_entitlement_process_all",
                ),
            )
        poi_missing = int(gaps.get("missing_poi") or 0)
        poi_total = int(gaps.get("poi_candidate_total") or 0)
        if poi_total > 0 and poi_missing > max(50, int(poi_total * 0.05)):
            pct = poi_missing * 100 // poi_total
            issues.append(
                OpsIssue(
                    code=f"missing_poi_{cf}",
                    severity="info",
                    message=(
                        f"{poi_missing} qualified POI candidates in {cf} "
                        f"missing OSM POI ({pct}%)"
                    ),
                    metric=gaps,
                    fix_action="refresh_poi_batch",
                ),
            )
        funnel_backlog = int(gaps.get("pipeline_funnel_backlog") or 0)
        if funnel_backlog > 20 and workers.get("ok"):
            issues.append(
                OpsIssue(
                    code=f"pipeline_backlog_{cf}",
                    severity="info",
                    message=(
                        f"{funnel_backlog} prescreen-qualified parcels in {cf} "
                        "need pipeline scoring"
                    ),
                    metric=gaps,
                    fix_action="enqueue_incomplete_limited",
                ),
            )

    summary = export_readiness_summary(db)
    backlog = int((summary.get("parcels_pipeline_funnel_backlog") or {}).get("count") or 0)
    address_gap = summary.get("parcels_missing_baltimore_candidate_street_address") or {}
    candidate_address_backlog = int(address_gap.get("count") or 0) if isinstance(address_gap, dict) else 0
    if candidate_address_backlog > 0 and workers.get("ok") and int(queues.get("parking_depth") or 0) == 0:
        issues.append(
            OpsIssue(
                code="baltimore_candidate_address_backlog",
                severity="info",
                message=(
                    f"{candidate_address_backlog} Baltimore deal candidates need street/map addresses; "
                    "use Realproperty first, then AddressPoint_Native fallback for source gaps"
                ),
                metric=address_gap if isinstance(address_gap, dict) else {"count": candidate_address_backlog},
                fix_action="backfill_baltimore_candidate_addresses",
            ),
        )
    if backlog > 50 and workers.get("ok"):
        issues.append(
            OpsIssue(
                code="pipeline_funnel_backlog",
                severity="info",
                message=f"{backlog} parcels in pipeline funnel backlog",
                metric={"count": backlog},
                fix_action="enqueue_incomplete_limited",
            ),
        )

    return issues


def _enqueue(task_fn: Any, *args: Any, **kwargs: Any) -> tuple[str | None, str]:
    try:
        async_result = task_fn.delay(*args, **kwargs)
        return async_result.id, "enqueued"
    except Exception as exc:
        return None, str(exc)[:200]


def apply_remediation(
    db: Session,
    settings: Settings,
    issues: list[OpsIssue],
    *,
    auto_fix: bool,
) -> list[RemediationAction]:
    from app.tasks import (
        backfill_baltimore_property_addresses_batch,
        enqueue_incomplete_pipeline_jobs,
        refresh_demand_distances_batch,
        refresh_entitlement_scores_batch,
        refresh_poi_density_batch,
        site_watchdog_check,
    )

    actions: list[RemediationAction] = []
    cooldown_sec = settings.ops_remediation_cooldown_sec
    poi_limit = settings.ops_remediation_poi_batch_limit
    pipeline_limit = settings.ops_remediation_pipeline_enqueue_limit
    address_limit = settings.ops_remediation_address_backfill_limit

    # One action per fix type per run (dedupe issues)
    seen_actions: set[str] = set()
    for issue in issues:
        action = issue.fix_action
        if not action or action in seen_actions:
            continue
        seen_actions.add(action)

        if not auto_fix:
            actions.append(
                RemediationAction(action=action, status="skipped_disabled", detail="auto_fix off"),
            )
            continue

        if cooldown_active(settings, action):
            actions.append(
                RemediationAction(
                    action=action,
                    status="skipped_cooldown",
                    detail=f"cooldown {cooldown_sec}s active",
                ),
            )
            continue

        task_id: str | None = None
        status = "failed"
        detail = ""
        cf = (settings.ops_remediation_priority_county_fips or "24510").strip()

        try:
            if action == "run_site_watchdog":
                task_id, detail = _enqueue(site_watchdog_check)
                status = "enqueued" if task_id else "failed"
            elif action == "refresh_demand_process_all":
                task_id, detail = _enqueue(
                    refresh_demand_distances_batch,
                    limit=settings.ops_remediation_batch_limit,
                    county_fips=cf,
                    process_all=True,
                    refresh_identification=True,
                )
                status = "enqueued" if task_id else "failed"
            elif action == "refresh_entitlement_process_all":
                task_id, detail = _enqueue(
                    refresh_entitlement_scores_batch,
                    limit=settings.ops_remediation_batch_limit,
                    county_fips=cf,
                    process_all=True,
                    prescreen_qualified_only=True,
                )
                status = "enqueued" if task_id else "failed"
            elif action == "refresh_poi_batch":
                task_id, detail = _enqueue(
                    refresh_poi_density_batch,
                    limit=poi_limit,
                    county_fips=cf,
                    only_missing=True,
                    process_all=False,
                )
                if task_id:
                    status = "enqueued"
                else:
                    # Workers down or broker unreachable — run inline (Overpass from this host).
                    result = refresh_poi_density_batch(
                        limit=poi_limit,
                        county_fips=cf,
                        only_missing=True,
                        process_all=False,
                    )
                    detail = json.dumps(result)[:200]
                    status = "completed"
            elif action == "prune_poi_refresh_queue":
                result = prune_queued_poi_refresh_tasks(db, settings)
                detail = json.dumps(
                    {
                        "removed": result.get("removable"),
                        "revoked_task_ids": result.get("revoked_task_ids"),
                    },
                )[:200]
                status = "completed" if result.get("ok") else "failed"
            elif action == "enqueue_incomplete_limited":
                result = enqueue_incomplete_pipeline_jobs(pipeline_limit)
                detail = json.dumps(result)[:200]
                status = "completed"
            elif action == "backfill_baltimore_candidate_addresses":
                task_id, detail = _enqueue(
                    backfill_baltimore_property_addresses_batch,
                    limit=address_limit,
                    dry_run=False,
                )
                status = "enqueued" if task_id else "failed"
            else:
                detail = f"unknown action {action}"
        except Exception as exc:
            detail = str(exc)[:200]
            status = "failed"

        if status in ("enqueued", "completed"):
            set_cooldown(settings, action, seconds=cooldown_sec)

        actions.append(
            RemediationAction(
                action=action,
                status=status,
                detail=detail if detail != "enqueued" else f"task {task_id}",
                task_id=task_id,
            ),
        )

    return actions


def build_report(
    db: Session,
    settings: Settings,
    *,
    issues: list[OpsIssue],
    actions: list[RemediationAction],
) -> dict[str, Any]:
    workers = inspect_celery_workers()
    queues = inspect_redis_queues(settings)
    counties = {cf: county_data_gaps(db, cf) for cf in priority_county_fips()}
    critical = sum(1 for i in issues if i.severity == "critical")
    return {
        "checked_at": datetime.now(tz=UTC).isoformat(),
        "ok": critical == 0,
        "issue_count": len(issues),
        "critical_count": critical,
        "auto_fix_enabled": effective_auto_fix_enabled(settings),
        "auto_fix_requested": settings.ops_remediation_auto_fix,
        "db_writes_allowed": settings.ops_remediation_allow_db_writes,
        "celery_workers": workers,
        "redis_queues": queues,
        "priority_counties": counties,
        "issues": [asdict(i) for i in issues],
        "actions": [asdict(a) for a in actions],
        "export_readiness": export_readiness_summary(db),
    }


def build_slack_text(report: dict[str, Any], *, recovered: bool = False) -> str:
    if report.get("ok") and not report.get("issues"):
        if recovered:
            return (
                ":white_check_mark: *Ops remediation — recovered*\n"
                "No critical issues; priority market data looks healthy."
            )
        return (
            ":white_check_mark: *Ops remediation — all clear*\n"
            f"Checked {report.get('checked_at', '?')}"
        )

    lines = [
        ":wrench: *Ops remediation loop*",
        f"Checked {report.get('checked_at', '?')}",
        f"*{report.get('issue_count', 0)}* issue(s) ({report.get('critical_count', 0)} critical)",
        "",
    ]
    for item in report.get("issues") or []:
        if item.get("severity") == "info" and report.get("critical_count", 0) > 0:
            continue
        lines.append(f"• [{item.get('severity')}] *{item.get('code')}*: {item.get('message')}")
    actions = report.get("actions") or []
    if actions:
        lines.append("")
        lines.append("*Actions:*")
        for act in actions[:12]:
            lines.append(
                f"  – {act.get('action')}: {act.get('status')} — {act.get('detail', '')[:120]}",
            )
    workers = report.get("celery_workers") or {}
    if not workers.get("ok"):
        lines.append("")
        lines.append(
            "_Fix Celery first: `docker compose … ps` → ensure `worker` and `redis` are up, "
            "then re-run POST /internal/ops/run-now_",
        )
    return "\n".join(lines)[:3900]


def should_post_slack(
    settings: Settings,
    report: dict[str, Any],
    previous: dict[str, Any] | None,
) -> tuple[bool, bool]:
    now_ok = bool(report.get("ok")) and int(report.get("critical_count") or 0) == 0
    prev_critical = int(previous.get("critical_count") or 0) if previous else 0
    if int(report.get("critical_count") or 0) > 0:
        return True, False
    if prev_critical > 0 and now_ok:
        return True, True
    if int(report.get("issue_count") or 0) > 0 and settings.ops_remediation_notify_on_warnings:
        return True, False
    hours = settings.ops_remediation_heartbeat_hours
    if hours > 0 and now_ok:
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


def run_ops_remediation_loop(db: Session) -> dict[str, Any]:
    from app.load_governor import current_governor_state, refresh_load_governor

    settings = get_settings()
    if not settings.ops_remediation_enabled:
        return {"skipped": True, "reason": "ops_remediation_disabled"}

    previous = load_last_report(settings)
    issues = diagnose(db, settings)
    governor = current_governor_state(settings)
    auto_fix = effective_auto_fix_enabled(settings) and bool(
        governor.get("ops_autofix_allowed", True),
    )
    actions = apply_remediation(
        db,
        settings,
        issues,
        auto_fix=auto_fix,
    )
    report = build_report(db, settings, issues=issues, actions=actions)
    save_report(settings, report)
    governor = refresh_load_governor(settings, cached_ops_report=report)
    report["load_governor"] = governor

    channel = (settings.ops_remediation_slack_channel_id or "").strip() or watchdog_slack_channel(
        settings,
    )
    token = (settings.slack_bot_token or "").strip()
    if token and channel:
        post, recovered = should_post_slack(settings, report, previous)
        if post:
            from app.slack_digest import post_text_to_slack

            post_text_to_slack(
                settings,
                text=build_slack_text(report, recovered=recovered),
                channel_id=channel,
            )

    return report
