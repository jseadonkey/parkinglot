from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import ApprovalRequest, AuditLog, Parcel, ParcelScore, WorkflowRun
from app.deal_progress_board import DEAL_STAGE_LABELS, query_deal_progress_board
from app.ingest_status import build_ingest_status_snapshot
from app.pilot_scope_filter import parcel_in_scope_clause
from app.pipeline_gates import parcel_qualifies_for_human_gate
from app.scoring_profiles import (
    AGENT_ENTITLEMENT_NAME,
    AGENT_ENTITLEMENT_TAGLINE,
    AGENT_IDENTIFICATION_NAME,
    AGENT_IDENTIFICATION_TAGLINE,
    AGENT_STRATEGIC_NAME,
    AGENT_STRATEGIC_TAGLINE,
    ENTITLEMENT,
    IDENTIFICATION,
    STRATEGIC,
)
from parking_core.pilot import load_pilot_config

logger = logging.getLogger(__name__)

DEFAULT_DIGEST_WINDOW_MINUTES = 20


@dataclass(frozen=True)
class FunnelMetrics:
    in_scope_parcels: int
    total_parcels: int
    with_identification: int
    with_entitlement: int
    with_strategic: int
    dual_qualified: int
    with_parking_comp: int
    candidate_target: int | None
    ingest_phase: str
    ingest_headline: str


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


def _parcel_score_counts_since(db: Session, cutoff: datetime) -> dict[str, int]:
    stmt = (
        select(ParcelScore.score_profile, func.count())
        .where(ParcelScore.created_at >= cutoff)
        .group_by(ParcelScore.score_profile)
    )
    return {str(row[0]): int(row[1]) for row in db.execute(stmt).all()}


def _count_distinct_profile(db: Session, profile: str) -> int:
    n = db.scalar(
        select(func.count(func.distinct(ParcelScore.parcel_id))).where(
            ParcelScore.score_profile == profile,
        ),
    )
    return int(n or 0)


def _count_in_scope_with_comp(db: Session) -> int:
    n = db.scalar(
        select(func.count())
        .select_from(Parcel)
        .where(
            parcel_in_scope_clause(),
            Parcel.distance_to_nearest_comp_parking_m.isnot(None),
        ),
    )
    return int(n or 0)


def _count_dual_qualified(
    db: Session,
    *,
    min_entitlement: float,
    min_strategic: float,
) -> int:
    pairs = _paired_latest_scores(db)
    return sum(
        1
        for _p, ps_e, ps_s in pairs
        if parcel_qualifies_for_human_gate(
            float(ps_e.total_score),
            float(ps_s.total_score),
            min_entitlement=min_entitlement,
            min_strategic=min_strategic,
        )
    )


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


def _build_funnel_metrics(db: Session, settings: Settings) -> FunnelMetrics:
    pilot_ent = load_pilot_config(settings.pilot_config_path)
    pilot_str = load_pilot_config(settings.pilot_strategic_config_path)
    floor_ent = float(pilot_ent.scoring.qualified_min_score)
    floor_str = float(pilot_str.scoring.qualified_min_score)
    ingest = build_ingest_status_snapshot(db)
    return FunnelMetrics(
        in_scope_parcels=ingest.parcels_in_scope_db,
        total_parcels=ingest.parcels_total_db,
        with_identification=_count_distinct_profile(db, IDENTIFICATION),
        with_entitlement=_count_distinct_profile(db, ENTITLEMENT),
        with_strategic=_count_distinct_profile(db, STRATEGIC),
        dual_qualified=_count_dual_qualified(db, min_entitlement=floor_ent, min_strategic=floor_str),
        with_parking_comp=_count_in_scope_with_comp(db),
        candidate_target=ingest.candidate_feature_count,
        ingest_phase=ingest.phase,
        ingest_headline=ingest.headline,
    )


def _format_window_label(window_minutes: int) -> str:
    if window_minutes >= 60 and window_minutes % 60 == 0:
        h = window_minutes // 60
        return f"{h}h" if h > 1 else "1h"
    return f"{window_minutes}m"


def build_slack_digest_blocks(
    db: Session,
    *,
    window_minutes: int = DEFAULT_DIGEST_WINDOW_MINUTES,
    hours: int | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Return Block Kit blocks plus plain-text fallback for the digest channel."""
    if hours is not None:
        window_minutes = max(1, hours * 60)
    cutoff = datetime.now(tz=UTC) - timedelta(minutes=window_minutes)
    window_label = _format_window_label(window_minutes)
    settings = get_settings()
    funnel = _build_funnel_metrics(db, settings)
    pilot_ent = load_pilot_config(settings.pilot_config_path)
    pilot_str = load_pilot_config(settings.pilot_strategic_config_path)
    floor_ent = float(pilot_ent.scoring.qualified_min_score)
    floor_str = float(pilot_str.scoring.qualified_min_score)
    region = pilot_ent.region.name

    new_parcel_rows = _count_since(db, Parcel, Parcel.created_at, cutoff)
    ingest_batches = _count_audit_action_since(db, "parcels_ingested", cutoff)
    score_by_profile = _parcel_score_counts_since(db, cutoff)
    total_score_rows = sum(score_by_profile.values())
    wf_by_status = _workflow_status_since(db, cutoff)
    pending = _pending_approvals(db)
    audit_lines = _recent_audit_lines(db, cutoff)
    failed_n = int(
        db.scalar(
            select(func.count())
            .select_from(WorkflowRun)
            .where(and_(WorkflowRun.updated_at >= cutoff, WorkflowRun.status == "failed")),
        )
        or 0,
    )

    stage_counts, _ = query_deal_progress_board(
        db,
        qualified_min_entitlement=floor_ent,
        qualified_min_strategic=floor_str,
        limit=1,
    )
    stage_lines = [
        f"• {DEAL_STAGE_LABELS.get(k, k)}: *{v}*"
        for k, v in sorted(stage_counts.items(), key=lambda kv: kv[1], reverse=True)
        if v > 0
    ]
    stage_block = "\n".join(stage_lines) if stage_lines else "• _(no in-scope parcels with pipeline runs yet)_"

    if wf_by_status:
        wf_lines = [f"• `{k}`: {v}" for k, v in sorted(wf_by_status.items())]
    else:
        wf_lines = ["• _(no workflow activity in this window)_"]

    score_parts = [f"`{k}`: {v}" for k, v in sorted(score_by_profile.items())]
    score_summary = ", ".join(score_parts) if score_parts else "none"

    load_pct = ""
    if funnel.candidate_target and funnel.candidate_target > 0:
        pct = min(100, int(100 * funnel.in_scope_parcels / funnel.candidate_target))
        load_pct = f" (*{pct}%* of ~{funnel.candidate_target:,} candidate target)"

    audit_block = "\n".join(audit_lines) if audit_lines else "_(no audit events in this window)_"
    ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    header = f"{region} — last {window_label} ({cutoff:%H:%M} → now UTC)"
    fallback = (
        f"Kent pilot digest — {header}\n"
        f"In-scope {funnel.in_scope_parcels}{load_pct} | "
        f"Id/Ent/Str scores: {funnel.with_identification}/{funnel.with_entitlement}/{funnel.with_strategic} | "
        f"Dual-qualified: {funnel.dual_qualified} | Pending approvals: {pending}"
    )

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Kent pilot — agent update", "emoji": True},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_{header}_ · _{ts}_"}],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Funnel load (cheap → expensive)*\n"
                    f"• Status: *{funnel.ingest_headline}* (`{funnel.ingest_phase}`)\n"
                    f"• In-scope parcels in DB: *{funnel.in_scope_parcels:,}*{load_pct}\n"
                    f"• Total parcel rows (in + out of scope): *{funnel.total_parcels:,}*\n"
                    "_Bulk ingest writes Cartographer prescreen scores only; Atlas + Beacon run in pipeline._"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Three scoring agents (coverage)*\n"
                    f"• *{AGENT_IDENTIFICATION_NAME}* (prescreen at ingest): "
                    f"*{funnel.with_identification:,}* — roll/zoning/lot/corner, *no* parking comps yet\n"
                    f"• *{AGENT_ENTITLEMENT_NAME}* (pipeline, POI demand): "
                    f"*{funnel.with_entitlement:,}* — floor *{floor_ent:.0f}*\n"
                    f"• *{AGENT_STRATEGIC_NAME}* (pipeline, gated comps): "
                    f"*{funnel.with_strategic:,}* — floor *{floor_str:.0f}*\n"
                    f"• Dual-qualified (Atlas + Beacon both ≥ floors): *{funnel.dual_qualified:,}*\n"
                    f"• Parcels with parking comp lookup applied: *{funnel.with_parking_comp:,}* "
                    "_(entitlement ≥ floor + surface zoning + building ≤ 70%)_"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Activity in last {window_label}*\n"
                    f"• New parcel rows: *{new_parcel_rows}* · ingest batches: *{ingest_batches}*\n"
                    f"• Score rows written: *{total_score_rows}* ({score_summary})\n"
                    f"• Pipeline runs updated:\n" + "\n".join(wf_lines) + f"\n• Failures: *{failed_n}*"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Deal progress (in-scope, latest run per parcel)*\n" + stage_block,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Human gate*\n"
                    f"Pending approvals (memo / contract): *{pending}*\n"
                    "_Operator console → Deals / Approvals_"
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Recent audit*\n" + audit_block},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "_Scheduled digest every 20m UTC. Daily dual-qualified report 14:00 UTC; "
                        "Atlas/Beacon discussion 15:30 UTC (agents channel). "
                        "Replies here do not reach the system — see docs/SLACK.md._"
                    ),
                },
            ],
        },
    ]
    return blocks, fallback


def _rationale_line(
    breakdown: dict[str, Any],
    *,
    total: float,
    floor: float,
    qualified: bool,
    profile: str | None = None,
    pilot_snapshot: dict[str, Any] | None = None,
) -> str:
    """Short operator-facing line from deterministic score breakdown JSON."""
    z = float(breakdown.get("zoning_component") or 0)
    lot_sz = float(breakdown.get("lot_size_component") or 0)
    c = float(breakdown.get("corner_component") or 0)
    d = float(breakdown.get("demand_proximity_component") or 0)
    bits: list[str] = []
    bits.append("zoning" if z > 0 else "no zoning credit")
    bits.append("lot size" if lot_sz > 0 else "lot below min / missing")
    bits.append("corner" if c > 0 else "not corner")

    snap = pilot_snapshot if isinstance(pilot_snapshot, dict) else {}
    signal = str(snap.get("demand_signal_source") or "")
    if profile == STRATEGIC:
        if d > 0 and signal == "comp":
            bits.append("near paid parking comp")
        elif d > 0:
            bits.append("market proximity (check comp gate)")
        else:
            bits.append("no comp credit (gated, outside buffer, or missing)")
    elif profile == ENTITLEMENT:
        bits.append("POI demand" if d > 0 else "POI demand weak/missing")
    elif profile == IDENTIFICATION:
        bits.append("prescreen only (no comp at ingest)" if d == 0 else "demand signal present")
    else:
        bits.append("near demand" if d > 0 else "demand distance weak/missing")

    notes = breakdown.get("notes") or []
    note_tail = ""
    if notes:
        note_tail = " _" + " ".join(str(n) for n in notes[:3]) + "_"
    q = "meets floor" if qualified else "below floor"
    return f"*{total:.0f}/100* ({q}, floor *{floor:.0f}*) — {', '.join(bits)}.{note_tail}"


def _fetch_latest_scores_per_parcel(db: Session, *, profile: str = ENTITLEMENT) -> list[tuple[Parcel, ParcelScore]]:
    """One latest ParcelScore row per in-scope parcel for a score profile."""
    agg = (
        select(ParcelScore.parcel_id, func.max(ParcelScore.created_at).label("mx"))
        .where(ParcelScore.score_profile == profile)
        .group_by(ParcelScore.parcel_id)
        .subquery()
    )
    stmt = (
        select(Parcel, ParcelScore)
        .join(ParcelScore, Parcel.id == ParcelScore.parcel_id)
        .where(parcel_in_scope_clause())
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
    """In-scope parcels with latest entitlement and strategic scores."""
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
    """Daily report: dual-qualified parcels, near-misses, and sample screened-out rows."""
    pilot_ent = load_pilot_config(settings.pilot_config_path)
    pilot_str = load_pilot_config(settings.pilot_strategic_config_path)
    floor_ent = float(pilot_ent.scoring.qualified_min_score)
    floor_str = float(pilot_str.scoring.qualified_min_score)
    region = pilot_ent.region.name
    funnel = _build_funnel_metrics(db, settings)

    pairs = _paired_latest_scores(db)
    dual: list[tuple[Parcel, ParcelScore, ParcelScore]] = []
    atlas_only: list[tuple[Parcel, ParcelScore, ParcelScore]] = []
    beacon_only: list[tuple[Parcel, ParcelScore, ParcelScore]] = []
    neither: list[tuple[Parcel, ParcelScore, ParcelScore]] = []

    for parcel, ps_e, ps_s in pairs:
        de = float(ps_e.total_score)
        ds = float(ps_s.total_score)
        e_ok = de >= floor_ent
        s_ok = ds >= floor_str
        if e_ok and s_ok:
            dual.append((parcel, ps_e, ps_s))
        elif e_ok:
            atlas_only.append((parcel, ps_e, ps_s))
        elif s_ok:
            beacon_only.append((parcel, ps_e, ps_s))
        else:
            neither.append((parcel, ps_e, ps_s))

    dual.sort(key=lambda t: float(t[1].total_score) + float(t[2].total_score), reverse=True)
    atlas_only.sort(key=lambda t: float(t[1].total_score), reverse=True)
    beacon_only.sort(key=lambda t: float(t[2].total_score), reverse=True)
    neither.sort(key=lambda t: float(t[1].total_score) + float(t[2].total_score), reverse=True)

    dual = dual[:max_qualified]
    atlas_only = atlas_only[: max(4, max_unqualified // 3)]
    beacon_only = beacon_only[: max(4, max_unqualified // 3)]
    neither = neither[: max(4, max_unqualified // 3)]

    ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

    def dual_line(parcel: Parcel, ps_e: ParcelScore, ps_s: ParcelScore) -> str:
        comp_note = ""
        if parcel.distance_to_nearest_comp_parking_m is not None:
            comp_note = f" · comp {parcel.distance_to_nearest_comp_parking_m:.0f}m"
        return (
            f"• `{parcel.apn}` — Atlas *{float(ps_e.total_score):.0f}* · "
            f"Beacon *{float(ps_s.total_score):.0f}*{comp_note}"
        )

    def split_line(parcel: Parcel, ps_e: ParcelScore, ps_s: ParcelScore, *, kind: str) -> str:
        bd = ps_s.breakdown if kind == "beacon" and isinstance(ps_s.breakdown, dict) else {}
        if kind == "atlas" and isinstance(ps_e.breakdown, dict):
            bd = ps_e.breakdown
        snap = ps_s.pilot_snapshot if kind == "beacon" else ps_e.pilot_snapshot
        prof = STRATEGIC if kind == "beacon" else ENTITLEMENT
        floor = floor_str if kind == "beacon" else floor_ent
        total = float(ps_s.total_score if kind == "beacon" else ps_e.total_score)
        ok = total >= floor
        rationale = _rationale_line(
            bd if isinstance(bd, dict) else {},
            total=total,
            floor=floor,
            qualified=ok,
            profile=prof,
            pilot_snapshot=snap if isinstance(snap, dict) else None,
        )
        return f"• `{parcel.apn}` — Atlas *{float(ps_e.total_score):.0f}* · Beacon *{float(ps_s.total_score):.0f}* — {rationale}"

    dual_body = "\n".join(dual_line(p, e, s) for p, e, s in dual) if dual else "_(none yet)_"
    atlas_body = "\n".join(split_line(p, e, s, kind="atlas") for p, e, s in atlas_only) if atlas_only else "_(none)_"
    beacon_body = "\n".join(split_line(p, e, s, kind="beacon") for p, e, s in beacon_only) if beacon_only else "_(none)_"
    low_body = "\n".join(split_line(p, e, s, kind="atlas") for p, e, s in neither[:max_unqualified]) if neither else "_(none)_"

    fallback = (
        f"Dual-qualified report ({region}) — {len(dual)} shown · "
        f"{funnel.dual_qualified} total dual-qualified · {ts}"
    )

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Dual-qualified parcels — daily report", "emoji": True},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"_{region}_ · Atlas floor *{floor_ent:.0f}* · Beacon floor *{floor_str:.0f}* · "
                        f"{funnel.in_scope_parcels:,} in-scope · {funnel.with_parking_comp:,} with comp data · _{ts}_"
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
                    "*Dual-qualified* (both agents ≥ floor — outreach candidates)\n"
                    + _trim_mrkdwn(dual_body)
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Atlas-led near-miss* (entitlement passes, Beacon below floor)\n"
                    + _trim_mrkdwn(atlas_body, 900)
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Beacon-led near-miss* (strategic passes, Atlas below floor — often missing comp gate)\n"
                    + _trim_mrkdwn(beacon_body, 900)
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Below both floors* (sample)\n" + _trim_mrkdwn(low_body, 900),
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "_Beacon strategic scores may lack comp points until entitlement + building gates pass. "
                        "Cartographer identification scores at ingest are prescreen only. "
                        "Operator console → Outreach / Deals._"
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
    """Sequential Slack messages: Atlas, Beacon, then joint comparison."""
    pilot_ent = load_pilot_config(settings.pilot_config_path)
    pilot_str = load_pilot_config(settings.pilot_strategic_config_path)
    floor_ent = float(pilot_ent.scoring.qualified_min_score)
    floor_str = float(pilot_str.scoring.qualified_min_score)
    ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    funnel = _build_funnel_metrics(db, settings)

    pairs = _paired_latest_scores(db)
    if not pairs:
        fb = f"Dual-agent channel — no parcels with both Atlas + Beacon scores yet · {ts}"
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Scoring agents — waiting for pipeline", "emoji": True},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"_{AGENT_IDENTIFICATION_NAME}_ has prescreened *{funnel.with_identification:,}* parcels at ingest. "
                        f"*{AGENT_ENTITLEMENT_NAME}* and *{AGENT_STRATEGIC_NAME}* need the scoring pipeline "
                        f"({funnel.with_entitlement:,} / {funnel.with_strategic:,} so far). "
                        "Bulk load enqueues pipelines in batches — refresh after ingest catches up."
                    ),
                },
            },
        ]
        return [(blocks, fb)]

    pairs.sort(key=lambda t: float(t[1].total_score), reverse=True)
    atlas_lines: list[str] = []
    for parcel, ps_e, _ps_s in pairs[:max_lines]:
        bd = ps_e.breakdown if isinstance(ps_e.breakdown, dict) else {}
        snap = ps_e.pilot_snapshot if isinstance(ps_e.pilot_snapshot, dict) else None
        qualifies_ent = float(ps_e.total_score) >= floor_ent
        line = _rationale_line(
            bd,
            total=float(ps_e.total_score),
            floor=floor_ent,
            qualified=qualifies_ent,
            profile=ENTITLEMENT,
            pilot_snapshot=snap,
        )
        atlas_lines.append(f"• `{parcel.apn}` — {line}")
    atlas_body = "\n".join(atlas_lines) if atlas_lines else "_(none)_"

    pairs_beacon = sorted(pairs, key=lambda t: float(t[2].total_score), reverse=True)
    beacon_lines: list[str] = []
    for parcel, _ps_e, ps_s in pairs_beacon[:max_lines]:
        bd = ps_s.breakdown if isinstance(ps_s.breakdown, dict) else {}
        snap = ps_s.pilot_snapshot if isinstance(ps_s.pilot_snapshot, dict) else None
        qualifies_str = float(ps_s.total_score) >= floor_str
        comp_tag = " · comp applied" if parcel.distance_to_nearest_comp_parking_m is not None else " · no comp yet"
        line = _rationale_line(
            bd,
            total=float(ps_s.total_score),
            floor=floor_str,
            qualified=qualifies_str,
            profile=STRATEGIC,
            pilot_snapshot=snap,
        )
        beacon_lines.append(f"• `{parcel.apn}`{comp_tag} — {line}")
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
            consensus.append(f"• `{parcel.apn}` — Atlas *{de:.0f}* · Beacon *{ds:.0f}* → *outreach*")
        elif e_ok and not s_ok:
            atlas_only.append(
                f"• `{parcel.apn}` — Atlas *{de:.0f}* vs Beacon *{ds:.0f}* "
                "_(zoning/POI strong; comp gate or market weak)_"
            )
        elif s_ok and not e_ok:
            beacon_only.append(
                f"• `{parcel.apn}` — Beacon *{ds:.0f}* vs Atlas *{de:.0f}* _(market signal without entitlement floor)_"
            )
    consensus_blk = "\n".join(consensus) if consensus else "_(none)_"
    atlas_ok_blk = "\n".join(atlas_only[:max_lines]) if atlas_only else "_(none)_"
    beacon_ok_blk = "\n".join(beacon_only[:max_lines]) if beacon_only else "_(none)_"
    joint_parts = [
        f"*Dual-qualified* ({funnel.dual_qualified} total)\n" + consensus_blk,
        "\n\n*Atlas-led* (entitlement clears, Beacon below)\n" + atlas_ok_blk,
        "\n\n*Beacon-led* (strategic clears, Atlas below)\n" + beacon_ok_blk,
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
                        f"_{AGENT_ENTITLEMENT_TAGLINE}_ · POI demand, not parking comps · "
                        f"floor *{floor_ent:.0f}* · _{ts}_"
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
                    f"*My ranking* (highest Atlas score among parcels both agents scored). "
                    f"_Talking to {AGENT_STRATEGIC_NAME}: I overweight zoning + POI proximity; "
                    f"your comp lens may disagree on pads I like on paper._*\n"
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
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"_{AGENT_STRATEGIC_TAGLINE}_ · paid parking comps (gated) · "
                        f"floor *{floor_str:.0f}* · _{ts}_"
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
                    f"*My ranking* (highest Beacon score first). "
                    f"_Replying to {AGENT_ENTITLEMENT_NAME}: comp lookup runs only after your floor + "
                    f"building-share gate — many rows show 0 comp credit until then._*\n"
                    + _trim_mrkdwn(beacon_body)
                ),
            },
        },
    ]
    fb2 = f"{AGENT_STRATEGIC_NAME} — top parcels · {ts}"

    post3: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Joint comparison — outreach vs near-miss", "emoji": True},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"_{len(pairs)} parcel(s) with both scores_ · "
                        f"Atlas *{floor_ent:.0f}* · Beacon *{floor_str:.0f}* · "
                        f"{funnel.with_parking_comp} with comp data · _{ts}_"
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
                        "_Deterministic scores — not an LLM debate. "
                        f"{AGENT_IDENTIFICATION_NAME} prescreen at ingest is separate. "
                        "Tune weights in config/pilot*.yaml._"
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
