from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import ApprovalRequest, AuditLog, Parcel, ParcelScore, WorkflowRun
from app.export_readiness import export_readiness_summary
from app.pilot_scope import COUNTY_DISPLAY_NAMES, pilot_scope_summary
from app.scoring_profiles import (
    AGENT_ENTITLEMENT_NAME,
    AGENT_ENTITLEMENT_TAGLINE,
    AGENT_STRATEGIC_NAME,
    AGENT_STRATEGIC_TAGLINE,
    ENTITLEMENT,
    STRATEGIC,
)
from app.site_watchdog import watchdog_slack_channel
from parking_core.pilot import load_pilot_config

logger = logging.getLogger(__name__)

BALTIMORE_CITY_FIPS = "24510"
BALTIMORE_CITY_PILOT_CAP = 20_000


def _count_since(db: Session, model: type, column: Any, cutoff: datetime) -> int:
    n = db.scalar(select(func.count()).select_from(model).where(column >= cutoff))
    return int(n or 0)


def _count_audit_action_since(db: Session, action: str, cutoff: datetime) -> int:
    n = db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(and_(AuditLog.action == action, AuditLog.created_at >= cutoff)),
    )
    return int(n or 0)


def _ingest_activity_since(db: Session, cutoff: datetime) -> dict[str, int]:
    """Totals from audit rows written by ``ingest_geojson_path`` (action ``parcels_ingested``)."""
    stmt = select(AuditLog.meta).where(
        and_(AuditLog.action == "parcels_ingested", AuditLog.created_at >= cutoff),
    )
    runs = 0
    inserted = 0
    updated = 0
    skipped = 0
    for (meta,) in db.execute(stmt).all():
        runs += 1
        block = meta if isinstance(meta, dict) else {}
        inserted += int(block.get("inserted") or 0)
        updated += int(block.get("updated") or 0)
        skipped += int(block.get("skipped") or 0)
    merge = _merge_activity_since(db, cutoff)
    return {
        "runs": runs,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "merge_runs": merge["runs"],
        "merge_updated": merge["updated"],
        "merge_not_found": merge["not_found"],
    }


def _merge_activity_since(db: Session, cutoff: datetime) -> dict[str, int]:
    """Totals from ``merge_parcel_attributes_geojson`` (action ``parcels_merge_attributes``)."""
    stmt = select(AuditLog.meta).where(
        and_(AuditLog.action == "parcels_merge_attributes", AuditLog.created_at >= cutoff),
    )
    runs = 0
    updated = 0
    not_found = 0
    for (meta,) in db.execute(stmt).all():
        runs += 1
        block = meta if isinstance(meta, dict) else {}
        updated += int(block.get("updated") or 0)
        not_found += int(block.get("not_found") or 0)
    return {"runs": runs, "updated": updated, "not_found": not_found}


def _parcel_score_counts_since(db: Session, cutoff: datetime) -> dict[str, int]:
    stmt = (
        select(ParcelScore.score_profile, func.count())
        .where(ParcelScore.created_at >= cutoff)
        .group_by(ParcelScore.score_profile)
    )
    return {str(row[0]): int(row[1]) for row in db.execute(stmt).all()}


def _pending_approvals(db: Session) -> int:
    n = db.scalar(
        select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.status == "pending"),
    )
    return int(n or 0)


def _workflow_status_since(db: Session, cutoff: datetime) -> dict[str, int]:
    stmt = (
        select(WorkflowRun.status, func.count())
        .select_from(WorkflowRun)
        .where(WorkflowRun.updated_at >= cutoff)
        .group_by(WorkflowRun.status)
    )
    return {str(row[0]): int(row[1]) for row in db.execute(stmt).all()}


def _recent_audit_lines(db: Session, cutoff: datetime, limit: int = 8) -> list[str]:
    stmt = select(AuditLog).where(AuditLog.created_at >= cutoff).order_by(AuditLog.created_at.desc()).limit(limit)
    lines: list[str] = []
    for row in db.scalars(stmt):
        lines.append(f"• *{row.actor}* — `{row.action}` ({row.entity_type})")
    return lines


def _recent_failed_workflow_lines(db: Session, cutoff: datetime, *, limit: int = 3) -> list[str]:
    stmt = (
        select(WorkflowRun, Parcel.apn)
        .join(Parcel, Parcel.id == WorkflowRun.parcel_id)
        .where(and_(WorkflowRun.updated_at >= cutoff, WorkflowRun.status == "failed"))
        .order_by(WorkflowRun.updated_at.desc())
        .limit(limit)
    )
    lines: list[str] = []
    for run, apn in db.execute(stmt):
        err = (run.error or "").strip().replace("\n", " ")
        if len(err) > 120:
            err = err[:117] + "…"
        tail = f" — _{err}_" if err else ""
        lines.append(f"• `{apn}` — step `{run.current_step or '?'}`{tail}")
    return lines


def _progress_bar(complete_pct: float, *, width: int = 8) -> str:
    pct = max(0.0, min(100.0, complete_pct))
    filled = int(round(width * pct / 100.0))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {pct:.0f}%"


def _coverage_progress_line(total: int, missing: int, label: str) -> str:
    if total <= 0:
        return f"• {label}: —"
    have = max(0, total - missing)
    return f"• {label}: *{have}/{total}* {_progress_bar(100.0 * have / total)}"


def _recent_ingest_audit_lines(db: Session, cutoff: datetime, *, limit: int = 3) -> list[str]:
    stmt = (
        select(AuditLog)
        .where(and_(AuditLog.action == "parcels_ingested", AuditLog.created_at >= cutoff))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    lines: list[str] = []
    for row in db.scalars(stmt):
        meta = row.meta if isinstance(row.meta, dict) else {}
        label = Path(str(meta.get("source_path") or "ingest")).name
        ins = int(meta.get("inserted") or 0)
        upd = int(meta.get("updated") or 0)
        sk = int(meta.get("skipped") or 0)
        when = row.created_at.strftime("%H:%M UTC") if row.created_at else "?"
        county = str(meta.get("default_county_fips") or "").strip()
        county_bit = ""
        if county:
            cname = COUNTY_DISPLAY_NAMES.get(county, county)
            county_bit = f" · {cname} `{county}`"
        lines.append(
            f"  ◦ `{label}` at {when}{county_bit} — +*{ins}* new, *{upd}* updated, *{sk}* skipped"
        )
    return lines


def _recent_merge_audit_lines(db: Session, cutoff: datetime, *, limit: int = 2) -> list[str]:
    stmt = (
        select(AuditLog)
        .where(and_(AuditLog.action == "parcels_merge_attributes", AuditLog.created_at >= cutoff))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    lines: list[str] = []
    for row in db.scalars(stmt):
        meta = row.meta if isinstance(row.meta, dict) else {}
        label = Path(str(meta.get("source_path") or "overlay")).name
        upd = int(meta.get("updated") or 0)
        nf = int(meta.get("not_found") or 0)
        when = row.created_at.strftime("%H:%M UTC") if row.created_at else "?"
        lines.append(f"  ◦ `{label}` at {when} — *{upd}* parcels got zoning/attrs, *{nf}* APN not in DB")
    return lines


def _county_zoning_fill(db: Session, county_fips: str) -> tuple[int, int]:
    total = db.scalar(
        select(func.count()).select_from(Parcel).where(Parcel.county_fips == county_fips),
    )
    total = int(total or 0)
    if total <= 0:
        return 0, 0
    with_code = db.scalar(
        select(func.count())
        .select_from(Parcel)
        .where(
            Parcel.county_fips == county_fips,
            Parcel.zoning_code.isnot(None),
            func.trim(Parcel.zoning_code) != "",
        ),
    )
    return total, int(with_code or 0)


def _ingest_window_interpretation(
    *,
    hours: int,
    new_parcel_rows: int,
    ingest: dict[str, int],
) -> str:
    ins = int(ingest.get("inserted") or 0)
    upd = int(ingest.get("updated") or 0)
    runs = int(ingest.get("runs") or 0)
    merge_runs = int(ingest.get("merge_runs") or 0)
    if runs == 0 and merge_runs == 0 and new_parcel_rows == 0:
        return (
            f"_No ingest or overlay merge in the last {hours}h. "
            "Run Baltimore fetch (`POST /internal/ingest/baltimore-city`) or widen "
            "`SLACK_DIGEST_WINDOW_HOURS`._"
        )
    if new_parcel_rows == 0 and ins == 0 and upd > 0:
        return (
            "_Re-ingest refreshed existing APNs only — `parcels.created_at` stays old, so "
            "“new parcel rows” stays 0 even when many features were processed._"
        )
    if new_parcel_rows == 0 and ins > 0:
        return "_New inserts happened but none in this time window (check a longer window)._"
    if merge_runs > 0 and int(ingest.get("merge_not_found") or 0) > 0:
        return (
            "_Some overlay features did not match a parcel row (wrong APN prefix or ingest not run yet)._"
        )
    return ""


def build_ingest_agent_mrkdwn(
    db: Session,
    settings: Settings,
    *,
    hours: int,
    cutoff: datetime,
    ingest: dict[str, int],
    new_parcel_rows: int,
) -> str:
    """Ingest-agent slice of the standup: sources, market progress, and window metrics."""
    parts: list[str] = [
        "_Loads parcel polygons and attributes into Postgres for scoring. "
        "Hourly window is global (all counties), not filtered to the priority market._",
        "\n*Data sources (project)*",
        "• *Baltimore City* (`24510`) — EGIS parcel layer + CityView zoning overlay (Phase B merge)",
        "• *Washington* (`53*`) — WaTech county GeoJSON, ~1 county / 7d when statewide rollout is on",
        "• *Manual* — `POST /internal/ingest/geojson-upload` or server-path GeoJSON",
    ]
    wa_on = bool(settings.wa_statewide_rollout_enabled)
    parts.append(
        f"• WA statewide Beat ingest: *{'on' if wa_on else 'off (Baltimore-first)'}*"
    )

    try:
        scope = pilot_scope_summary(db)
        parts.append(f"\n*Load progress — {scope['primary_market_name']}*")
        for fips in scope.get("priority_county_fips") or []:
            row = next((c for c in scope["counties"] if c["county_fips"] == fips), None)
            n = int(row["parcels_in_db"]) if row else 0
            name = COUNTY_DISPLAY_NAMES.get(fips, fips)
            if fips == BALTIMORE_CITY_FIPS:
                bar = _progress_bar(100.0 * n / BALTIMORE_CITY_PILOT_CAP if BALTIMORE_CITY_PILOT_CAP else 0)
                total_b, zoned = _county_zoning_fill(db, fips)
                z_pct = f"{100.0 * zoned / total_b:.0f}%" if total_b else "—"
                parts.append(
                    f"• *{name}* `{fips}`: *{n}* / ~{BALTIMORE_CITY_PILOT_CAP:,} parcels {bar}\n"
                    f"  Zoning on rows: *{zoned}/{total_b}* ({z_pct}) — needs Phase B overlay merge"
                )
            else:
                parts.append(f"• *{name}* `{fips}`: *{n}* parcels in DB")
        king_n = next(
            (c["parcels_in_db"] for c in scope["counties"] if c["county_fips"] == "53033"),
            0,
        )
        if king_n:
            parts.append(f"• *King County WA* (`53033`, legacy bulk): *{king_n:,}* parcels")
    except Exception:
        logger.exception("pilot_scope_summary failed in ingest agent block")
        parts.append("\n*Load progress:* _(could not load pilot scope)_")

    parts.append(
        f"\n*Last {hours}h window*\n"
        f"• New parcel rows (`parcels.created_at` in window): *{new_parcel_rows}*\n"
        "  _First-time inserts only; upserts to existing APNs do not count._\n"
        f"• Ingest runs (audit `parcels_ingested`): *{ingest['runs']}* → "
        f"+*{ingest['inserted']}* inserted, *{ingest['updated']}* refreshed, "
        f"*{ingest['skipped']}* skipped\n"
        f"• Overlay merges (audit `parcels_merge_attributes`): *{ingest['merge_runs']}* → "
        f"*{ingest.get('merge_updated', 0)}* rows updated, "
        f"*{ingest.get('merge_not_found', 0)}* APN not found"
    )
    hint = _ingest_window_interpretation(hours=hours, new_parcel_rows=new_parcel_rows, ingest=ingest)
    if hint:
        parts.append(hint)
    recent_ingest = _recent_ingest_audit_lines(db, cutoff)
    if recent_ingest:
        parts.append("*Recent ingest files:*\n" + "\n".join(recent_ingest))
    recent_merge = _recent_merge_audit_lines(db, cutoff)
    if recent_merge:
        parts.append("*Recent overlay merges:*\n" + "\n".join(recent_merge))

    sched = (settings.scheduled_geojson_ingest_path or "").strip()
    if sched:
        parts.append(f"• Scheduled file ingest (Beat): `{Path(sched).name}`")

    return _trim_mrkdwn("\n".join(parts), 2900)


def build_data_gathering_progress_mrkdwn(db: Session) -> str:
    """Operator-facing summary: what data we collect, where, and how complete it is."""
    parts: list[str] = [
        "*What we're gathering*\n"
        "Paid surface-parking candidates: parcel *footprints & APN*, *lot size*, *zoning*, "
        "*demand distance*, *scores* (prescreen → Atlas → Beacon), and *owner outreach* "
        "briefs for export.",
    ]

    try:
        scope = pilot_scope_summary(db)
        counties_with_data = [c for c in scope["counties"] if c["parcels_in_db"] > 0]
        counties_with_data.sort(key=lambda c: c["parcels_in_db"], reverse=True)
        parts.append(
            f"\n*Geography — {scope['region_name']}*\n"
            f"• Counties with parcel data: *{scope['counties_with_ingested_parcels']}* / "
            f"*{scope['pilot_county_count']}* pilot counties\n"
            f"• Parcels in pilot scope: *{scope['parcels_in_pilot_counties']}* · "
            f"priority *{scope['primary_market_name']}*: "
            f"*{scope['parcels_in_priority_counties']}*"
        )
        if counties_with_data:
            bits = [f"{c['county_name']} *{c['parcels_in_db']}*" for c in counties_with_data[:6]]
            parts.append("• Top loaded: " + ", ".join(bits))
            if len(counties_with_data) > 6:
                parts.append(f"  _…and {len(counties_with_data) - 6} more counties_")
        else:
            parts.append(
                "• _No pilot-county parcels yet — use Baltimore / WaTech fetch + ingest APIs._"
            )
    except Exception:
        logger.exception("pilot_scope_summary failed in Slack digest")
        parts.append("\n*Geography:* _(could not load pilot scope)_")

    summary = export_readiness_summary(db)
    total = int(summary.get("parcel_row_total") or 0)
    if total <= 0:
        parts.append("\n*Coverage:* database empty — load sample or run county ingest.")
    else:
        parts.append(f"\n*Data layer progress* ({total} parcels)")
        parts.append(
            _coverage_progress_line(
                total,
                int((summary.get("parcels_missing_footprint") or {}).get("count") or 0),
                "Footprints",
            )
        )
        parts.append(
            _coverage_progress_line(
                total,
                int((summary.get("parcels_missing_zoning_code") or {}).get("count") or 0),
                "Zoning",
            )
        )
        parts.append(
            _coverage_progress_line(
                total,
                int((summary.get("parcels_missing_distance_to_nearest_demand_m") or {}).get("count") or 0),
                "Demand distance",
            )
        )
        parts.append(
            _coverage_progress_line(
                total,
                int((summary.get("parcels_missing_score_identification") or {}).get("count") or 0),
                "Prescreen scores",
            )
        )
        parts.append(
            _coverage_progress_line(
                total,
                int((summary.get("parcels_missing_score_entitlement") or {}).get("count") or 0),
                "Atlas (entitlement)",
            )
        )
        parts.append(
            _coverage_progress_line(
                total,
                int((summary.get("parcels_missing_score_strategic") or {}).get("count") or 0),
                "Beacon (strategic)",
            )
        )
        parts.append(
            _coverage_progress_line(
                total,
                int((summary.get("parcels_missing_owner_outreach_brief") or {}).get("count") or 0),
                "Owner outreach brief",
            )
        )
        pq = int((summary.get("parcels_prescreen_qualified") or {}).get("count") or 0)
        backlog = int((summary.get("parcels_pipeline_funnel_backlog") or {}).get("count") or 0)
        ruled_p = int((summary.get("parcels_ruled_out_by_prescreen") or {}).get("count") or 0)
        ruled_a = int((summary.get("parcels_ruled_out_at_atlas") or {}).get("count") or 0)
        parts.append(
            f"\n*Scoring funnel*\n"
            f"• Passed prescreen: *{pq}* · awaiting pipeline: *{backlog}*\n"
            f"• Ruled out at prescreen / Atlas: *{ruled_p}* / *{ruled_a}*"
        )
        steps = summary.get("recommended_next_steps") or []
        if steps and backlog > 0:
            parts.append(f"_Suggested next step:_ {steps[0]}")

    return _trim_mrkdwn("\n".join(parts), 2900)


def slack_reporting_catalog(settings: Settings | None = None) -> list[dict[str, str]]:
    """Inventory of automated Slack posts (for status API and digest footer)."""
    s = settings or get_settings()
    digest_ch = (s.slack_digest_channel_id or "").strip() or "(unset)"
    agent_ch = (s.slack_agent_discussion_channel_id or "").strip() or "(unset)"
    wd_ch = watchdog_slack_channel(s) or digest_ch

    rows: list[dict[str, str]] = [
        {
            "id": "standup",
            "schedule_utc": f"crontab hour={s.slack_digest_crontab_hour} minute={s.slack_digest_crontab_minute:02d}",
            "channel": digest_ch,
            "description": f"Hourly pipeline standup ({s.slack_digest_window_hours}h window)",
        },
        {
            "id": "qualified_parcels",
            "schedule_utc": "daily 14:00",
            "channel": digest_ch,
            "description": "Qualified vs below-floor parcels with score rationale",
        },
        {
            "id": "dual_agent",
            "schedule_utc": "daily 15:30",
            "channel": agent_ch,
            "description": "Atlas + Beacon rankings and joint comparison (3 messages)",
        },
    ]
    if s.site_watchdog_enabled:
        hb = s.site_watchdog_heartbeat_hours
        rows.append(
            {
                "id": "site_watchdog",
                "schedule_utc": f"every hour at :{s.site_watchdog_crontab_minute}",
                "channel": wd_ch,
                "description": (
                    "API/DB/Redis/UI health; alerts on failure, recovery, "
                    f"and all-clear heartbeat every {hb}h when green"
                ),
            },
        )
    if slack_agent_event_updates_enabled(s):
        rows.append(
            {
                "id": "agent_events",
                "schedule_utc": "on each ingest/pipeline task",
                "channel": digest_ch,
                "description": "Per-job lines (SLACK_AGENT_EVENT_UPDATES)",
            },
        )
    rows.append(
        {
            "id": "deploy_notify",
            "schedule_utc": "GitHub Deploy workflow (optional)",
            "channel": digest_ch,
            "description": "POST /internal/slack/test-message after deploy",
        },
    )
    return rows


def _operator_links_mrkdwn(settings: Settings) -> str:
    base = (settings.api_public_url or "").strip().rstrip("/")
    if not base or base.startswith("http://localhost"):
        return "_Set `PUBLIC_API_URL` in deploy/.env for quick links in Slack._"
    return (
        f"• API docs: <{base}/docs|OpenAPI>\n"
        f"• Export readiness: <{base}/internal/stats/export-readiness|JSON> "
        "(requires `X-Internal-Key`)"
    )


def build_slack_digest_blocks(
    db: Session,
    *,
    hours: int = 4,
    settings: Settings | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Return Block Kit blocks plus a plain-text fallback for notifications."""
    settings = settings or get_settings()
    cutoff = datetime.now(tz=UTC) - timedelta(hours=hours)
    try:
        pilot = load_pilot_config(settings.pilot_config_path)
        region_label = pilot.region.name
    except Exception:
        region_label = "pilot"
    new_parcel_rows = _count_since(db, Parcel, Parcel.created_at, cutoff)
    ingest = _ingest_activity_since(db, cutoff)
    ingest_batches = ingest["runs"]
    score_by_profile = _parcel_score_counts_since(db, cutoff)
    total_score_rows = sum(score_by_profile.values())
    total_parcels = db.scalar(select(func.count()).select_from(Parcel))
    total_parcels = int(total_parcels or 0)
    wf_by_status = _workflow_status_since(db, cutoff)
    pending = _pending_approvals(db)
    audit_lines = _recent_audit_lines(db, cutoff)
    failed_n = db.scalar(
        select(func.count())
        .select_from(WorkflowRun)
        .where(and_(WorkflowRun.updated_at >= cutoff, WorkflowRun.status == "failed")),
    )
    failed_n = int(failed_n or 0)
    failed_lines = _recent_failed_workflow_lines(db, cutoff)
    gathering_body = build_data_gathering_progress_mrkdwn(db)
    ingest_body = build_ingest_agent_mrkdwn(
        db,
        settings,
        hours=hours,
        cutoff=cutoff,
        ingest=ingest,
        new_parcel_rows=new_parcel_rows,
    )

    if wf_by_status:
        wf_lines = [f"• `{k}`: {v}" for k, v in sorted(wf_by_status.items())]
    else:
        wf_lines = ["• _(no `workflow_runs.updated_at` in this window)_"]

    score_parts = [f"`{k}`: {v}" for k, v in sorted(score_by_profile.items())]
    score_summary = ", ".join(score_parts) if score_parts else "none"

    audit_block = "\n".join(audit_lines) if audit_lines else "_(no audit events in this window)_"

    header = (
        f"{region_label} — {hours}h standup ({cutoff:%Y-%m-%d %H:%M} → now UTC)"
    )
    fallback = (
        f"{header}\n"
        f"Data: +{ingest['inserted']} new / {ingest['updated']} updated parcels ({ingest_batches} ingest jobs) | "
        f"DB total={total_parcels} | scores written={total_score_rows} | "
        f"pending approvals={pending} | workflow failures={failed_n}"
    )
    failed_detail = (
        "\n".join(failed_lines)
        if failed_lines
        else "_(no failed runs in this window)_"
    )
    catalog_lines = [
        f"• *{r['id']}* — {r['schedule_utc']} — {r['description']}"
        for r in slack_reporting_catalog(settings)
    ]

    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Parking agents — standup", "emoji": True}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_{header}_ · region *{region_label}_",
                },
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Data gathering & progress*\n" + gathering_body,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Ingest agent*\n" + ingest_body,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Pipeline activity (last {hours}h)*\n"
                    f"• Workflow runs by status:\n"
                    + "\n".join(wf_lines)
                    + f"\n• New score rows written: *{total_score_rows}* ({score_summary})\n"
                    f"• Parcels in DB (all counties): *{total_parcels}*\n"
                    f"• Failures: *{failed_n}*\n{failed_detail}"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Human-gate coordinator*\n"
                    f"*Pending* approval requests (needs a person): *{pending}*\n"
                    "_Use the approval UI or `GET /approvals?status=pending`._\n\n"
                    + _operator_links_mrkdwn(settings)
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Ops / audit log (snippet)*\n" + audit_block},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Other Slack reports (this stack)*\n" + "\n".join(catalog_lines),
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "_Scheduled digest · replying does not reach agents · "
                        "`GET /internal/slack/status` lists config · docs/SLACK.md_"
                    ),
                },
            ],
        },
    ]
    return blocks, fallback


def _rationale_line(breakdown: dict[str, Any], *, total: float, floor: float, qualified: bool) -> str:
    """Short operator-facing line from deterministic score breakdown JSON."""
    z = float(breakdown.get("zoning_component") or 0)
    lot_sz = float(breakdown.get("lot_size_component") or 0)
    c = float(breakdown.get("corner_component") or 0)
    d = float(breakdown.get("demand_proximity_component") or 0)
    p = float(breakdown.get("parking_market_component") or 0)
    bits: list[str] = []
    bits.append("zoning" if z > 0 else "no zoning credit")
    bits.append("lot size" if lot_sz > 0 else "lot below min / missing")
    bits.append("corner" if c > 0 else "not corner")
    bits.append("near demand" if d > 0 else "demand distance weak/missing")
    bits.append(f"parking market +{p:.0f}" if p > 0 else "no parking comp credit")
    notes = breakdown.get("notes") or []
    note_tail = ""
    if notes:
        note_tail = " _" + " ".join(str(n) for n in notes[:4]) + "_"
    q = "meets floor" if qualified else "below floor"
    return f"*{total:.0f}/100* ({q}, floor *{floor:.0f}*) — {', '.join(bits)}.{note_tail}"


def _fetch_latest_scores_per_parcel(db: Session, *, profile: str = ENTITLEMENT) -> list[tuple[Parcel, ParcelScore]]:
    """One latest ParcelScore row per parcel for a score profile (by created_at)."""
    agg = (
        select(ParcelScore.parcel_id, func.max(ParcelScore.created_at).label("mx"))
        .where(ParcelScore.score_profile == profile)
        .group_by(ParcelScore.parcel_id)
        .subquery()
    )
    stmt = (
        select(Parcel, ParcelScore)
        .join(ParcelScore, Parcel.id == ParcelScore.parcel_id)
        .join(
            agg,
            and_(
                ParcelScore.parcel_id == agg.c.parcel_id,
                ParcelScore.created_at == agg.c.mx,
                ParcelScore.score_profile == profile,
            ),
        )
    )
    return list(db.execute(stmt).all())


def _paired_latest_scores(db: Session) -> list[tuple[Parcel, ParcelScore, ParcelScore]]:
    """Parcels that have a latest entitlement score and a latest strategic score."""
    ent_rows = _fetch_latest_scores_per_parcel(db, profile=ENTITLEMENT)
    str_rows = _fetch_latest_scores_per_parcel(db, profile=STRATEGIC)
    by_ent = {p.id: (p, ps) for p, ps in ent_rows}
    by_str = {p.id: (p, ps) for p, ps in str_rows}
    common = by_ent.keys() & by_str.keys()
    out: list[tuple[Parcel, ParcelScore, ParcelScore]] = []
    for pid in common:
        p1, e = by_ent[pid]
        _, s = by_str[pid]
        out.append((p1, e, s))
    return out


def _trim_mrkdwn(s: str, cap: int = 2800) -> str:
    if len(s) <= cap:
        return s
    return s[: cap - 3] + "…"


def build_qualified_parcels_report_blocks(
    db: Session,
    *,
    settings: Settings,
    max_qualified: int = 20,
    max_unqualified: int = 12,
) -> tuple[list[dict[str, Any]], str]:
    """Block Kit report: parcels with latest scores vs pilot qualified_min_score, with rationale."""
    pilot = load_pilot_config(settings.pilot_config_path)
    floor = float(pilot.scoring.qualified_min_score)
    region = pilot.region.name

    rows = _fetch_latest_scores_per_parcel(db, profile=ENTITLEMENT)
    qualified_all: list[tuple[Parcel, ParcelScore]] = []
    unqualified_all: list[tuple[Parcel, ParcelScore]] = []
    for parcel, ps in rows:
        if float(ps.total_score) >= floor:
            qualified_all.append((parcel, ps))
        else:
            unqualified_all.append((parcel, ps))
    n_qualified_total = len(qualified_all)
    n_unqualified_total = len(unqualified_all)
    qualified = sorted(qualified_all, key=lambda x: float(x[1].total_score), reverse=True)[:max_qualified]
    unqualified = sorted(unqualified_all, key=lambda x: float(x[1].total_score), reverse=True)[:max_unqualified]

    ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    fallback = (
        f"Qualified parcels report ({region}) — floor {floor:.0f} — "
        f"{n_qualified_total} qualified / {n_unqualified_total} below floor "
        f"(showing up to {max_qualified}/{max_unqualified}) — {ts}"
    )

    def lines_for(pairs: list[tuple[Parcel, ParcelScore]], *, ok: bool) -> str:
        out: list[str] = []
        for parcel, ps in pairs:
            bd = ps.breakdown if isinstance(ps.breakdown, dict) else {}
            line = _rationale_line(bd, total=float(ps.total_score), floor=floor, qualified=ok)
            out.append(f"• `{parcel.apn}` ({parcel.county_fips}) — {line}")
        return "\n".join(out) if out else "_(none in this list)_"

    q_body = lines_for(qualified, ok=True)
    u_body = lines_for(unqualified, ok=False)

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Qualified parcels — scoring agent", "emoji": True},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"_{region}_ · pilot floor *{floor:.0f}* (`qualified_min_score`) · "
                        f"*{n_qualified_total}* qualified · *{n_unqualified_total}* below floor · "
                        f"{len(rows)} scored parcel(s) · _{ts}_"
                    ),
                },
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Qualified* (latest score ≥ floor)\n" + _trim_mrkdwn(q_body),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Not qualified* (sample, below floor — why)\n" + _trim_mrkdwn(u_body),
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "_Scores are deterministic from ingest flags + pilot weights in `config/pilot.yaml`. "
                        "API: `GET /parcels?qualified_only=true`._"
                    ),
                },
            ],
        },
    ]
    return blocks, fallback


def post_digest_to_slack(settings: Settings, blocks: list[dict[str, Any]], fallback: str) -> dict[str, Any]:
    channel = (settings.slack_digest_channel_id or "").strip()
    return post_blocks_to_slack_channel(settings, channel_id=channel, blocks=blocks, fallback=fallback)


def post_blocks_to_slack_channel(
    settings: Settings,
    *,
    channel_id: str,
    blocks: list[dict[str, Any]],
    fallback: str,
) -> dict[str, Any]:
    token = (settings.slack_bot_token or "").strip()
    channel = (channel_id or "").strip()
    if not token or not channel:
        raise ValueError("slack not configured")
    client = WebClient(token=token)
    try:
        resp = client.chat_postMessage(channel=channel, blocks=blocks, text=fallback)
        return {"ok": resp.get("ok"), "ts": resp.get("ts"), "channel": resp.get("channel")}
    except SlackApiError as e:
        logger.exception("Slack API error posting blocks")
        raise RuntimeError(e.response.get("error", str(e))) from e


def build_dual_agent_discussion_posts(
    db: Session,
    *,
    settings: Settings,
    max_lines: int = 14,
) -> list[tuple[list[dict[str, Any]], str]]:
    """Sequential Slack messages: Atlas, Beacon, then joint comparison (same channel, not a thread)."""
    pilot_ent = load_pilot_config(settings.pilot_config_path)
    pilot_str = load_pilot_config(settings.pilot_strategic_config_path)
    floor_ent = float(pilot_ent.scoring.qualified_min_score)
    floor_str = float(pilot_str.scoring.qualified_min_score)
    ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

    pairs = _paired_latest_scores(db)
    if not pairs:
        fb = f"Dual-agent channel — no parcels with both scores yet · {ts}"
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Scoring agents — waiting for data", "emoji": True},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "_Atlas_ (entitlement / `pilot.yaml`) and _Beacon_ (strategic / `pilot_strategic.yaml`) "
                        "both need a fresh score per parcel. Re-run **`POST /parcels/{id}/pipeline/run`** or ingest "
                        "with auto-pipeline so each parcel gets *two* `parcel_scores` rows."
                    ),
                },
            },
        ]
        return [(blocks, fb)]

    pairs.sort(key=lambda t: float(t[1].total_score), reverse=True)
    atlas_lines: list[str] = []
    for parcel, ps_e, _ps_s in pairs[:max_lines]:
        bd = ps_e.breakdown if isinstance(ps_e.breakdown, dict) else {}
        qualifies_ent = float(ps_e.total_score) >= floor_ent
        line = _rationale_line(
            bd,
            total=float(ps_e.total_score),
            floor=floor_ent,
            qualified=qualifies_ent,
        )
        atlas_lines.append(f"• `{parcel.apn}` ({parcel.county_fips}) — {line}")
    atlas_body = "\n".join(atlas_lines) if atlas_lines else "_(none)_"

    pairs_beacon = sorted(pairs, key=lambda t: float(t[2].total_score), reverse=True)
    beacon_lines: list[str] = []
    for parcel, _ps_e, ps_s in pairs_beacon[:max_lines]:
        bd = ps_s.breakdown if isinstance(ps_s.breakdown, dict) else {}
        qualifies_str = float(ps_s.total_score) >= floor_str
        line = _rationale_line(
            bd,
            total=float(ps_s.total_score),
            floor=floor_str,
            qualified=qualifies_str,
        )
        beacon_lines.append(f"• `{parcel.apn}` ({parcel.county_fips}) — {line}")
    beacon_body = "\n".join(beacon_lines) if beacon_lines else "_(none)_"

    consensus: list[str] = []
    atlas_only: list[str] = []
    beacon_only: list[str] = []
    for parcel, ps_e, ps_s in pairs:
        e_ok = float(ps_e.total_score) >= floor_ent
        s_ok = float(ps_s.total_score) >= floor_str
        de = float(ps_e.total_score)
        ds = float(ps_s.total_score)
        if e_ok and s_ok:
            consensus.append(f"• `{parcel.apn}` — Atlas *{de:.0f}* · Beacon *{ds:.0f}*")
        elif e_ok and not s_ok:
            atlas_only.append(
                f"• `{parcel.apn}` — Atlas *{de:.0f}* vs Beacon *{ds:.0f}* "
                "_(zoning-weighted vs demand-weighted)_"
            )
        elif s_ok and not e_ok:
            beacon_only.append(f"• `{parcel.apn}` — Beacon *{ds:.0f}* vs Atlas *{de:.0f}* _(location wins here)_")
    consensus_blk = "\n".join(consensus) if consensus else "_(none)_"
    atlas_ok_blk = "\n".join(atlas_only[:max_lines]) if atlas_only else "_(none)_"
    beacon_ok_blk = "\n".join(beacon_only[:max_lines]) if beacon_only else "_(none)_"
    joint_parts = [
        "*Strong consensus* (both ≥ their floors)\n" + consensus_blk,
        "\n\n*Atlas-led* (entitlement clears, Beacon below floor)\n" + atlas_ok_blk,
        "\n\n*Beacon-led* (demand/strategic clears, Atlas below floor)\n" + beacon_ok_blk,
    ]
    joint_body = _trim_mrkdwn("".join(joint_parts), 2900)

    post1: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{AGENT_ENTITLEMENT_NAME} — picks", "emoji": True},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"_{AGENT_ENTITLEMENT_TAGLINE}_ · floor *{floor_ent:.0f}* · _{ts}_"
                    ),
                },
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*My ranking* (highest Atlas score first among parcels both agents scored). "
                    f"_Talking to {AGENT_STRATEGIC_NAME}: I overweight zoning + clear lot rules; "
                    f"your lens should surface pads I might underrate if demand is strong._*\n"
                    + _trim_mrkdwn(atlas_body)
                ),
            },
        },
    ]
    fb1 = f"{AGENT_ENTITLEMENT_NAME} — top parcels · {ts}"

    post2: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{AGENT_STRATEGIC_NAME} — picks", "emoji": True},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_{AGENT_STRATEGIC_TAGLINE}_ · floor *{floor_str:.0f}* · _{ts}_"}],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*My ranking* (highest Beacon score first). "
                    f"_Replying to {AGENT_ENTITLEMENT_NAME}: I pull demand + corner visibility harder; "
                    f"some of your top zoning plays look weak on revenue site quality to me._*\n"
                    + _trim_mrkdwn(beacon_body)
                ),
            },
        },
    ]
    fb2 = f"{AGENT_STRATEGIC_NAME} — top parcels · {ts}"

    post3: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Joint comparison — who agrees", "emoji": True},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"_{len(pairs)} parcel(s) with both scores_ · "
                        f"Atlas floor *{floor_ent:.0f}* · Beacon floor *{floor_str:.0f}* · _{ts}_"
                    ),
                },
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": joint_body},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "_Deterministic scores only — not an LLM debate. "
                        "Tune weights in `config/pilot.yaml` and `config/pilot_strategic.yaml`._"
                    ),
                },
            ],
        },
    ]
    fb3 = f"Dual-agent joint comparison — {len(pairs)} parcels · {ts}"
    return [(post1, fb1), (post2, fb2), (post3, fb3)]


_AGENT_EVENT_TRUTHY = frozenset({"1", "true", "yes", "on"})


def slack_agent_event_updates_enabled(settings: Settings) -> bool:
    """Whether Celery tasks should post per-job Slack lines (see SLACK_AGENT_EVENT_UPDATES)."""
    raw = (settings.slack_agent_event_updates or "").strip().lower()
    return raw in _AGENT_EVENT_TRUTHY


def post_agent_event_to_slack(settings: Settings, *, agent: str, detail: str) -> None:
    """Best-effort one-line agent update; no-ops if Slack or agent events are off. Never raises."""
    if not slack_agent_event_updates_enabled(settings):
        return
    token = (settings.slack_bot_token or "").strip()
    channel = (settings.slack_digest_channel_id or "").strip()
    if not token or not channel:
        return
    text = f"*{agent}*\n{detail}"
    if len(text) > 3500:
        text = text[:3490] + "…"
    try:
        post_text_to_slack(settings, text=text)
    except Exception:
        logger.exception("Slack agent event post failed (non-fatal): %s", agent)


def post_text_to_slack(settings: Settings, *, text: str, channel_id: str | None = None) -> dict[str, Any]:
    token = (settings.slack_bot_token or "").strip()
    channel = (channel_id or settings.slack_digest_channel_id or "").strip()
    if not token or not channel:
        raise ValueError("slack not configured")
    client = WebClient(token=token)
    try:
        resp = client.chat_postMessage(channel=channel, text=text)
        return {"ok": resp.get("ok"), "ts": resp.get("ts"), "channel": resp.get("channel")}
    except SlackApiError as e:
        logger.exception("Slack API error posting message")
        raise RuntimeError(e.response.get("error", str(e))) from e
