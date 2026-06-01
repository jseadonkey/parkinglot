from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import ApprovalRequest, AuditLog, Parcel, ParcelScore, WorkflowRun
from app.scoring_profiles import (
    AGENT_ENTITLEMENT_NAME,
    AGENT_ENTITLEMENT_TAGLINE,
    AGENT_STRATEGIC_NAME,
    AGENT_STRATEGIC_TAGLINE,
    ENTITLEMENT,
    STRATEGIC,
)
from parking_core.pilot import load_pilot_config

logger = logging.getLogger(__name__)


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


def build_slack_digest_blocks(db: Session, *, hours: int = 4) -> tuple[list[dict[str, Any]], str]:
    """Return Block Kit blocks plus a plain-text fallback for notifications."""
    cutoff = datetime.now(tz=UTC) - timedelta(hours=hours)
    new_parcel_rows = _count_since(db, Parcel, Parcel.created_at, cutoff)
    ingest_batches = _count_audit_action_since(db, "parcels_ingested", cutoff)
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

    if wf_by_status:
        wf_lines = [f"• `{k}`: {v}" for k, v in sorted(wf_by_status.items())]
    else:
        wf_lines = ["• _(no `workflow_runs.updated_at` in this window)_"]

    score_parts = [f"`{k}`: {v}" for k, v in sorted(score_by_profile.items())]
    score_summary = ", ".join(score_parts) if score_parts else "none"

    audit_block = "\n".join(audit_lines) if audit_lines else "_(no audit events in this window)_"

    header = f"Parking acquisition — {hours}h standup ({cutoff:%Y-%m-%d %H:%M} → now UTC)"
    fallback = (
        f"{header}\n"
        f"Ingest: new rows={new_parcel_rows}, ingest batches={ingest_batches} | "
        f"parcel_scores written={total_score_rows} | Pending approvals: {pending} | "
        f"Workflow updates by status: {wf_by_status!s} | Failures: {failed_n}"
    )

    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Parking agents — standup", "emoji": True}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_{header}_",
                },
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Ingest agent*\n"
                    f"• New parcel *rows* (`parcels.created_at` in window): *{new_parcel_rows}*\n"
                    f"• Ingest *runs* (audit `parcels_ingested`): *{ingest_batches}*\n"
                    f"• Total parcels in DB: *{total_parcels}*\n"
                    "_GeoJSON ingest does not run by itself: call `POST /internal/ingest/geojson-upload`, "
                    "`/internal/ingest/geojson-server-path`, or set `SCHEDULED_GEOJSON_INGEST_PATH` "
                    "(Beat). Re-ingesting existing APNs updates rows but does **not** change `created_at`, "
                    "so use ingest batch count above for refresh activity._"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Scoring & pipeline agent*\n"
                    f"• Workflow runs touched in the last *{hours}h* (by `workflow_runs.updated_at` status):\n"
                    + "\n".join(wf_lines)
                    + f"\n• New `parcel_scores` rows (pipeline output): *{total_score_rows}* ({score_summary})"
                    + f"\n\n_Failures in window:_ *{failed_n}*"
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
                    "_Use the approval UI or `GET /approvals?status=pending`._"
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Ops / audit log (snippet)*\n" + audit_block},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "_This is a scheduled digest. Replying here does not reach the agents yet; "
                        "see docs/SLACK.md for two-way options._"
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
    bits: list[str] = []
    bits.append("zoning" if z > 0 else "no zoning credit")
    bits.append("lot size" if lot_sz > 0 else "lot below min / missing")
    bits.append("corner" if c > 0 else "not corner")
    bits.append("near demand" if d > 0 else "demand distance weak/missing")
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
    qualified: list[tuple[Parcel, ParcelScore]] = []
    unqualified: list[tuple[Parcel, ParcelScore]] = []
    for parcel, ps in rows:
        if float(ps.total_score) >= floor:
            qualified.append((parcel, ps))
        else:
            unqualified.append((parcel, ps))
    qualified.sort(key=lambda x: float(x[1].total_score), reverse=True)
    unqualified.sort(key=lambda x: float(x[1].total_score), reverse=True)
    qualified = qualified[:max_qualified]
    unqualified = unqualified[:max_unqualified]

    ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    fallback = (
        f"Qualified parcels report ({region}) — floor {floor:.0f} — "
        f"{len(qualified)} shown qualified, {len(unqualified)} shown not — {ts}"
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
                        f"{len(rows)} parcel(s) with a score · _{ts}_"
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
