from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geoalchemy2.elements import WKTElement
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import and_, case, delete, desc, exists, func, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.approvals_util import queue_approval
from app.audit import write_audit
from app.celery_app import celery
from app.config import get_settings
from app.contract_render import render_ground_lease_draft
from app.db.concurrent_writes import update_parcel_columns_if
from app.db.models import ContractDraft, DealMemo, OwnerCandidateRow, Parcel, ParcelScore, WorkflowRun
from app.db.session import SessionLocal
from app.exploration_campaign import (
    campaign_day_index,
    counties_for_exploration_day,
    load_campaign_config,
)
from app.geo_markets import priority_county_fips, wa_rollout_pacing
from app.memo_render import build_deal_memo_markdown
from app.outreach_contacts import sync_contact_points_from_brief
from app.owner_portfolio import count_qualified_peer_parcels
from app.parcel_deal_context import parcel_centroid_lat_lon, rate_comps_for_parcel
from app.pipeline_funnel import (
    entitlement_qualified_floor,
    filter_prescreen_qualified_ids,
    identification_prescreen_floor,
    identification_prescreen_qualified,
    needs_pipeline_scoring,
    owner_outreach_min_entitlement_score,
    owner_outreach_min_strategic_score,
    parcel_prescreen_qualified,
    strategic_qualified_floor,
)
from app.poi_density import (
    POI_DENSITY_CANDIDATE_MODE,
    select_poi_density_candidates,
)
from app.scoring_profiles import (
    ENTITLEMENT,
    IDENTIFICATION,
    PIPELINE_PROFILES,
    STRATEGIC,
)
from app.slack_digest import (
    build_dual_agent_discussion_posts,
    build_plan_progress_report_blocks,
    build_qualified_parcels_report_blocks,
    build_slack_digest_blocks,
    post_agent_event_to_slack,
    post_blocks_to_slack_channel,
    post_digest_to_slack,
    post_text_to_slack,
)
from app.storage import put_text_object
from app.wa_statewide_rollout import (
    load_rollout_config,
    merge_rollout_config,
    next_county_to_ingest,
    parcel_counts_by_county,
    parking_queue_depth,
    wa_rollout_cooldown_state,
    wa_rollout_pending_ingest_state,
)
from app.wa_zoning_followup import build_zoning_followup_summary
from app.zoning_entitlement import effective_zoning_code, parcel_zoning_symbol, parcel_zoning_tier
from parking_core.models import OwnerCandidate, ParcelFeature, ScoreResult
from parking_core.pilot import PilotConfig, load_pilot_config
from parking_enrichment.owner_normalize import scoped_owner_key
from parking_enrichment.owner_outreach_agent import build_owner_outreach_brief
from parking_enrichment.pipeline import enrich_from_parcel_row
from parking_enrichment.registry_lookup import lookup_secretary_of_state_stub
from parking_enrichment.vendor_lookup_client import fetch_vendor_owner_enrichment
from parking_scoring.engine import score_parcel
from parking_workflows.state import WorkflowStatus, WorkflowStep

logger = logging.getLogger(__name__)


def _record_wa_zoning_followups_after_ingest(
    db: Session,
    *,
    county_touches: dict[str, int],
    source_path: str,
) -> list[dict[str, Any]]:
    """Create an explicit zoning acquisition follow-up when WA parcels land without trusted zoning."""
    wa_counties = sorted(fips for fips, touched in county_touches.items() if fips.startswith("53") and touched > 0)
    if not wa_counties:
        return []

    settings = get_settings()
    counts = parcel_counts_by_county(db, wa_counties)
    summary = build_zoning_followup_summary(
        parcel_counts=counts,
        registry_path=settings.wa_jurisdiction_registry_path,
        priority_order=wa_counties,
    )
    followups = [row for row in summary.get("counties", []) if row.get("needs_followup")]
    if not followups:
        return []

    for row in followups:
        write_audit(
            db,
            actor="system",
            action="wa_zoning_followup_required",
            entity_type="county_fips",
            entity_id=str(row["county_fips"]),
            meta={
                "source_path": source_path,
                "parcels_touched_by_ingest": county_touches.get(str(row["county_fips"]), 0),
                "parcels_in_db": row.get("parcels_in_db"),
                "zoning_status": row.get("zoning_status"),
                "jurisdiction_count": row.get("jurisdiction_count"),
                "jurisdiction_status_counts": row.get("jurisdiction_status_counts"),
                "next_action": row.get("next_action"),
            },
        )

    from app.pilot_scope import COUNTY_DISPLAY_NAMES

    bullets: list[str] = []
    for row in followups[:5]:
        fips = str(row["county_fips"])
        name = COUNTY_DISPLAY_NAMES.get(fips, fips)
        bullets.append(
            f"• {name} (`{fips}`): {int(row.get('parcels_in_db') or 0):,} parcels · "
            f"zoning `{row.get('zoning_status')}` · next: {row.get('next_action')}"
        )
    extra = ""
    if len(followups) > len(bullets):
        extra = f"\n• +{len(followups) - len(bullets)} more county/counties."
    post_agent_event_to_slack(
        settings,
        agent="Zoning acquisition",
        detail=(
            "Parcel ingest found WA counties that still need trusted zoning sources/joins/QA.\n"
            + "\n".join(bullets)
            + extra
        ),
    )
    return followups


def enqueue_unscored_pipeline_jobs(limit: int = 100) -> dict[str, Any]:
    """Enqueue ``run_pipeline`` for prescreen-qualified parcels missing an entitlement score."""
    return enqueue_incomplete_pipeline_jobs(limit)

def enqueue_priority_qualified_pipeline_jobs(limit: int = 75) -> dict[str, Any]:
    """Enqueue pipeline for high-score owner outreach targets, highest entitlement first."""
    cap = min(max(limit, 1), 200)
    floor_i = identification_prescreen_floor()
    floor_ent = owner_outreach_min_entitlement_score()
    floor_str = owner_outreach_min_strategic_score()
    db = _session()
    try:
        ident_agg = (
            select(
                ParcelScore.parcel_id.label("pid"),
                func.max(ParcelScore.created_at).label("mx"),
            )
            .where(ParcelScore.score_profile == IDENTIFICATION)
            .group_by(ParcelScore.parcel_id)
            .subquery()
        )
        ident = (
            select(ParcelScore.parcel_id, ParcelScore.total_score.label("id_score"))
            .join(
                ident_agg,
                and_(
                    ParcelScore.parcel_id == ident_agg.c.pid,
                    ParcelScore.created_at == ident_agg.c.mx,
                ),
            )
            .where(
                ParcelScore.score_profile == IDENTIFICATION,
                ParcelScore.total_score >= floor_i,
            )
            .subquery()
        )
        ent_agg = (
            select(
                ParcelScore.parcel_id.label("pid"),
                func.max(ParcelScore.created_at).label("mx"),
            )
            .where(ParcelScore.score_profile == ENTITLEMENT)
            .group_by(ParcelScore.parcel_id)
            .subquery()
        )
        ent = (
            select(ParcelScore.parcel_id, ParcelScore.total_score.label("ent_score"))
            .join(
                ent_agg,
                and_(
                    ParcelScore.parcel_id == ent_agg.c.pid,
                    ParcelScore.created_at == ent_agg.c.mx,
                ),
            )
            .where(
                ParcelScore.score_profile == ENTITLEMENT,
                ParcelScore.total_score >= floor_ent,
            )
            .subquery()
        )
        str_agg = (
            select(
                ParcelScore.parcel_id.label("pid"),
                func.max(ParcelScore.created_at).label("mx"),
            )
            .where(ParcelScore.score_profile == STRATEGIC)
            .group_by(ParcelScore.parcel_id)
            .subquery()
        )
        strategic = (
            select(ParcelScore.parcel_id, ParcelScore.total_score.label("str_score"))
            .join(
                str_agg,
                and_(
                    ParcelScore.parcel_id == str_agg.c.pid,
                    ParcelScore.created_at == str_agg.c.mx,
                ),
            )
            .where(ParcelScore.score_profile == STRATEGIC)
            .subquery()
        )
        pri_counties = priority_county_fips()
        order_cols = [
            ent.c.ent_score.desc(),
            strategic.c.str_score.desc().nulls_last(),
            ident.c.id_score.desc(),
        ]
        if pri_counties:
            geo_first = case((Parcel.county_fips.in_(pri_counties), 0), else_=1)
            order_cols = [geo_first, *order_cols]
        stmt = (
            select(Parcel.id)
            .join(ident, Parcel.id == ident.c.parcel_id)
            .join(ent, Parcel.id == ent.c.parcel_id)
            .outerjoin(strategic, Parcel.id == strategic.c.parcel_id)
            .where(
                or_(
                    needs_pipeline_scoring(),
                    and_(
                        strategic.c.str_score >= floor_str,
                        Parcel.owner_outreach_brief.is_(None),
                    ),
                )
            )
            .order_by(*order_cols)
            .limit(cap)
        )
        ids = [str(i) for i in db.scalars(stmt)]
        for pid in ids:
            run_pipeline.delay(pid)
        return {
            "enqueued": len(ids),
            "parcel_ids": ids,
            "mode": "priority_owner_outreach_high_score",
            "prescreen_floor": floor_i,
            "entitlement_floor": floor_ent,
            "strategic_floor": floor_str,
            "priority_county_fips": pri_counties,
        }
    finally:
        db.close()


def enqueue_incomplete_pipeline_jobs(limit: int = 100) -> dict[str, Any]:
    """Enqueue ``run_pipeline`` for prescreen-qualified parcels missing entitlement or strategic."""
    cap = min(max(limit, 1), 500)
    floor_i = identification_prescreen_floor()
    db = _session()
    try:
        agg = (
            select(
                ParcelScore.parcel_id.label("pid"),
                func.max(ParcelScore.created_at).label("mx"),
            )
            .where(ParcelScore.score_profile == IDENTIFICATION)
            .group_by(ParcelScore.parcel_id)
            .subquery()
        )
        ident = (
            select(ParcelScore.parcel_id, ParcelScore.total_score.label("id_score"))
            .join(
                agg,
                and_(
                    ParcelScore.parcel_id == agg.c.pid,
                    ParcelScore.created_at == agg.c.mx,
                ),
            )
            .where(
                ParcelScore.score_profile == IDENTIFICATION,
                ParcelScore.total_score >= floor_i,
            )
            .subquery()
        )
        ent_agg = (
            select(
                ParcelScore.parcel_id.label("pid"),
                func.max(ParcelScore.created_at).label("mx"),
            )
            .where(ParcelScore.score_profile == ENTITLEMENT)
            .group_by(ParcelScore.parcel_id)
            .subquery()
        )
        ent = (
            select(ParcelScore.parcel_id, ParcelScore.total_score.label("ent_score"))
            .join(
                ent_agg,
                and_(
                    ParcelScore.parcel_id == ent_agg.c.pid,
                    ParcelScore.created_at == ent_agg.c.mx,
                ),
            )
            .where(ParcelScore.score_profile == ENTITLEMENT)
            .subquery()
        )
        stmt = (
            select(Parcel.id)
            .join(ident, Parcel.id == ident.c.parcel_id)
            .outerjoin(ent, Parcel.id == ent.c.parcel_id)
            .where(needs_pipeline_scoring())
            .order_by(
                ent.c.ent_score.desc().nulls_last(),
                ident.c.id_score.desc(),
            )
            .limit(cap)
        )
        ids = [str(i) for i in db.scalars(stmt)]
        for pid in ids:
            run_pipeline.delay(pid)
        return {
            "enqueued": len(ids),
            "parcel_ids": ids,
            "mode": "prescreen_qualified_missing_entitlement_or_strategic",
            "prescreen_floor": floor_i,
        }
    finally:
        db.close()


def _session() -> Session:
    return SessionLocal()


def _write_slack_digest_audit(
    *,
    channel: str,
    posted: dict[str, Any],
    fallback: str,
) -> None:
    """Write slack_digest_posted audit in a fresh session (read queries must not poison commit)."""
    audit_db = _session()
    try:
        write_audit(
            audit_db,
            actor="celery:slack_agent_digest",
            action="slack_digest_posted",
            entity_type="slack_channel",
            entity_id=channel,
            meta={
                "slack_ts": posted.get("ts"),
                "channel": posted.get("channel"),
                "fallback_preview": (fallback or "")[:240],
            },
        )
    except Exception:
        logger.exception("slack_digest_posted audit failed (Slack message may already be posted)")
    finally:
        audit_db.close()


def _parcel_feature(parcel: Parcel) -> ParcelFeature:
    raw = parcel.raw_properties if hasattr(parcel, "raw_properties") else None
    raw_dict = raw if isinstance(raw, dict) else None
    zoning_code = effective_zoning_code(parcel.zoning_code, raw_dict)
    symbol = parcel_zoning_symbol(
        county_fips=parcel.county_fips,
        zoning_code=zoning_code,
        raw_properties=raw_dict,
    )
    tier = parcel_zoning_tier(
        county_fips=parcel.county_fips,
        zoning_code=zoning_code,
        raw_properties=raw_dict,
    )
    return ParcelFeature(
        apn=parcel.apn,
        county_fips=parcel.county_fips,
        lot_sqft=parcel.lot_sqft,
        zoning_code=zoning_code,
        zoning_allows_surface_parking=parcel.zoning_allows_surface_parking,
        zoning_principal_use_symbol=symbol,
        zoning_entitlement_tier=tier,
        is_corner_lot=parcel.is_corner_lot,
        distance_to_nearest_demand_m=parcel.distance_to_nearest_demand_m,
        raw_properties=raw_dict,
    )


def _score_parcel_with_nearby_comps(
    db: Session,
    *,
    parcel: Parcel,
    pilot: PilotConfig,
) -> ScoreResult:
    """Score using merged DB + YAML paid parking comps when parcel has a footprint centroid."""
    feature = _parcel_feature(parcel)
    comps = []
    centroid = parcel_centroid_lat_lon(parcel)
    if centroid is not None:
        lat, lon = centroid
        comps = rate_comps_for_parcel(db, lat=lat, lon=lon, pilot=pilot)
    return score_parcel(feature, pilot, nearby_rate_comps=comps)


def _upsert_identification_score(db: Session, parcel: Parcel) -> None:
    """Persist ingest-time prescreen score (``identification`` profile)."""
    settings = get_settings()
    pilot_id = load_pilot_config(settings.pilot_identification_config_path)
    result = score_parcel(_parcel_feature(parcel), pilot_id)
    snap = dict(result.pilot_snapshot or {})
    snap["agent_role"] = "identification_prescreen"
    snap["agent_label"] = "Agent Cartographer"
    db.execute(
        delete(ParcelScore).where(
            ParcelScore.parcel_id == parcel.id,
            ParcelScore.score_profile == IDENTIFICATION,
        )
    )
    db.add(
        ParcelScore(
            id=uuid.uuid4(),
            parcel_id=parcel.id,
            score_profile=IDENTIFICATION,
            total_score=result.total_score,
            breakdown=result.breakdown.model_dump(),
            pilot_snapshot=snap,
        )
    )


def _upsert_entitlement_score(db: Session, parcel: Parcel) -> None:
    """Refresh Atlas entitlement score from parcel features (zoning, lot, demand, comps)."""
    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    result = _score_parcel_with_nearby_comps(db, parcel=parcel, pilot=pilot)
    snap = dict(result.pilot_snapshot or {})
    snap["agent_role"] = "entitlement_prescreen"
    snap["agent_label"] = "Agent Atlas (feature refresh)"
    result.pilot_snapshot = snap
    _persist_pipeline_score(db, parcel_id=parcel.id, profile=ENTITLEMENT, result=result)


def _to_multi(geom: Polygon | MultiPolygon) -> MultiPolygon:
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    return geom


def _persist_pipeline_score(
    db: Session,
    *,
    parcel_id: uuid.UUID,
    profile: str,
    result: Any,
) -> None:
    db.execute(
        delete(ParcelScore).where(
            ParcelScore.parcel_id == parcel_id,
            ParcelScore.score_profile == profile,
        )
    )
    db.add(
        ParcelScore(
            id=uuid.uuid4(),
            parcel_id=parcel_id,
            score_profile=profile,
            total_score=result.total_score,
            breakdown=result.breakdown.model_dump(),
            pilot_snapshot=result.pilot_snapshot,
        )
    )


def _complete_pipeline_scoring_only(
    db: Session,
    run: WorkflowRun,
    *,
    parcel_id: str,
    apn: str,
    reason: str,
    entitlement_score: float,
    strategic_score: float | None,
    entitlement_floor: float,
    strategic_floor: float,
) -> dict[str, Any]:
    run.status = WorkflowStatus.completed.value
    run.current_step = WorkflowStep.score.value
    db.add(run)
    db.commit()
    write_audit(
        db,
        actor="system",
        action="pipeline_scoring_ruled_out",
        entity_type="workflow_run",
        entity_id=str(run.id),
        meta={
            "parcel_id": parcel_id,
            "reason": reason,
            "entitlement_score": entitlement_score,
            "strategic_score": strategic_score,
        },
    )
    if reason == "below_entitlement_floor":
        detail = (
            f"Parcel `{apn}` — Atlas *{entitlement_score:.1f}* (below floor *{entitlement_floor:.0f}*); "
            "Beacon and enrichment skipped."
        )
    elif reason == "below_strategic_floor":
        detail = (
            f"Parcel `{apn}` — Atlas *{entitlement_score:.1f}*; "
            f"Beacon *{float(strategic_score or 0):.1f}* (below floor *{strategic_floor:.0f}*); "
            "enrichment skipped."
        )
    else:
        detail = (
            f"Parcel `{apn}` — Atlas *{entitlement_score:.1f}*; "
            f"Beacon *{float(strategic_score or 0):.1f}*; "
            f"below owner outreach floors (*{entitlement_floor:.0f}* / *{strategic_floor:.0f}*). "
            "Owner outreach brief skipped."
        )
    post_agent_event_to_slack(get_settings(), agent="Scoring & pipeline agent", detail=detail)
    return {
        "workflow_run_id": str(run.id),
        "status": run.status,
        "skipped_enrichment": True,
        "reason": reason,
        "entitlement_score": entitlement_score,
        "strategic_score": strategic_score,
    }


@celery.task(name="app.tasks.run_pipeline")
def run_pipeline(parcel_id: str) -> dict[str, Any]:
    db = _session()
    try:
        parcel = db.get(Parcel, uuid.UUID(parcel_id))
        if parcel is None:
            raise ValueError("parcel not found")
        if not parcel_prescreen_qualified(db, parcel.id):
            logger.info(
                "run_pipeline skipped parcel %s (identification prescreen below floor %s)",
                parcel_id,
                identification_prescreen_floor(),
            )
            return {
                "skipped": True,
                "reason": "below_identification_prescreen_floor",
                "parcel_id": parcel_id,
                "prescreen_floor": identification_prescreen_floor(),
            }
    finally:
        db.close()

    db = _session()
    wid = uuid.uuid4()
    run = WorkflowRun(
        id=wid,
        parcel_id=uuid.UUID(parcel_id),
        status=WorkflowStatus.running.value,
        current_step=WorkflowStep.score.value,
    )
    db.add(run)
    db.commit()
    try:
        parcel = db.get(Parcel, uuid.UUID(parcel_id))
        if parcel is None:
            run.status = WorkflowStatus.failed.value
            run.error = "parcel not found"
            db.add(run)
            db.commit()
            raise ValueError("parcel not found")
        settings = get_settings()
        pilot_ent = load_pilot_config(settings.pilot_config_path)
        pilot_str = load_pilot_config(settings.pilot_strategic_config_path)

        floor_ent = entitlement_qualified_floor()
        floor_str = strategic_qualified_floor()

        score = _score_parcel_with_nearby_comps(db, parcel=parcel, pilot=pilot_ent)
        _persist_pipeline_score(db, parcel_id=parcel.id, profile=ENTITLEMENT, result=score)
        db.commit()

        if float(score.total_score) < floor_ent:
            logger.info(
                "run_pipeline parcel %s Atlas %.1f below floor %.0f — skipping Beacon and enrichment",
                parcel_id,
                score.total_score,
                floor_ent,
            )
            return _complete_pipeline_scoring_only(
                db,
                run,
                parcel_id=parcel_id,
                apn=parcel.apn,
                reason="below_entitlement_floor",
                entitlement_score=float(score.total_score),
                strategic_score=None,
                entitlement_floor=floor_ent,
                strategic_floor=floor_str,
            )

        score_strategic = _score_parcel_with_nearby_comps(db, parcel=parcel, pilot=pilot_str)
        _persist_pipeline_score(db, parcel_id=parcel.id, profile=STRATEGIC, result=score_strategic)
        db.commit()

        if float(score_strategic.total_score) < floor_str:
            logger.info(
                "run_pipeline parcel %s Beacon %.1f below floor %.0f — skipping enrichment",
                parcel_id,
                score_strategic.total_score,
                floor_str,
            )
            return _complete_pipeline_scoring_only(
                db,
                run,
                parcel_id=parcel_id,
                apn=parcel.apn,
                reason="below_strategic_floor",
                entitlement_score=float(score.total_score),
                strategic_score=float(score_strategic.total_score),
                entitlement_floor=floor_ent,
                strategic_floor=floor_str,
            )

        owner_ent_floor = owner_outreach_min_entitlement_score()
        owner_str_floor = owner_outreach_min_strategic_score()
        if (
            float(score.total_score) < owner_ent_floor
            or float(score_strategic.total_score) < owner_str_floor
        ):
            logger.info(
                "run_pipeline parcel %s below owner outreach floors %.0f/%.0f "
                "(Atlas %.1f, Beacon %.1f) — skipping owner outreach brief",
                parcel_id,
                owner_ent_floor,
                owner_str_floor,
                score.total_score,
                score_strategic.total_score,
            )
            return _complete_pipeline_scoring_only(
                db,
                run,
                parcel_id=parcel_id,
                apn=parcel.apn,
                reason="below_owner_outreach_floor",
                entitlement_score=float(score.total_score),
                strategic_score=float(score_strategic.total_score),
                entitlement_floor=owner_ent_floor,
                strategic_floor=owner_str_floor,
            )

        run.current_step = WorkflowStep.enrich.value
        db.add(run)
        db.commit()

        db.execute(delete(OwnerCandidateRow).where(OwnerCandidateRow.parcel_id == parcel.id))
        enriched: list[OwnerCandidate] = list(enrich_from_parcel_row(parcel.raw_properties or {}))
        norm_key: str | None = None
        if enriched:
            norm_key = scoped_owner_key(enriched[0].display_name, county_fips=parcel.county_fips)
        for cand in enriched:
            db.add(
                OwnerCandidateRow(
                    id=uuid.uuid4(),
                    parcel_id=parcel.id,
                    display_name=cand.display_name,
                    kind=cand.kind.value,
                    confidence=cand.confidence,
                    source=cand.source,
                    raw=cand.raw,
                    normalized_owner_key=norm_key,
                )
            )

        floor = float(load_pilot_config(settings.pilot_config_path).scoring.qualified_min_score)
        peer_count, peer_examples = (0, [])
        if norm_key:
            peer_count, peer_examples = count_qualified_peer_parcels(
                db,
                parcel_id=parcel.id,
                normalized_owner_key=norm_key,
                entitlement_floor=floor,
            )

        registry = None
        if enriched:
            registry = lookup_secretary_of_state_stub(
                county_fips=parcel.county_fips,
                owner_kind=enriched[0].kind,
                query_name=enriched[0].display_name,
            )

        vendor = fetch_vendor_owner_enrichment(
            enabled=settings.owner_vendor_lookup_enabled,
            url=(settings.owner_vendor_lookup_url or "").strip() or None,
            api_key=(settings.owner_vendor_lookup_api_key or "").strip() or None,
            parcel_id=str(parcel.id),
            county_fips=parcel.county_fips,
            apn=parcel.apn,
            owners=[
                {"display_name": o.display_name, "kind": o.kind.value, "confidence": o.confidence}
                for o in enriched
            ],
        )

        outreach_brief = build_owner_outreach_brief(
            county_fips=parcel.county_fips,
            apn=parcel.apn,
            raw_properties=parcel.raw_properties or {},
            owners=enriched,
            normalized_owner_key=norm_key,
            registry_lookup=registry,
            vendor_lookup=vendor,
            same_owner_qualified_other_count=peer_count,
            same_owner_peer_examples=peer_examples,
        )
        parcel.owner_outreach_brief = outreach_brief.model_dump(mode="json")
        sync_contact_points_from_brief(db, parcel_id=parcel.id, brief=outreach_brief)
        db.add(parcel)
        db.commit()

        owners = db.query(OwnerCandidateRow).filter(OwnerCandidateRow.parcel_id == parcel.id).all()
        owner_lines = [f"{o.display_name} ({o.kind}, conf={o.confidence:.2f}, {o.source})" for o in owners]
        title, body_md, open_questions = build_deal_memo_markdown(
            apn=parcel.apn,
            county_fips=parcel.county_fips,
            zoning_code=parcel.zoning_code,
            lot_sqft=parcel.lot_sqft,
            score=score,
            owner_lines=owner_lines,
            outreach_brief=outreach_brief,
        )
        memo = DealMemo(
            id=uuid.uuid4(),
            parcel_id=parcel.id,
            title=title,
            body_md=body_md,
            open_questions=open_questions,
        )
        db.add(memo)

        primary_owner = owners[0].display_name if owners else "Unknown"
        contract_md = render_ground_lease_draft(
            apn=parcel.apn,
            county_fips=parcel.county_fips,
            owner_name=primary_owner,
            lot_sqft=parcel.lot_sqft,
        )
        key = f"contracts/{parcel.id}/draft-v1.md"
        put_text_object(key, contract_md)
        cd = ContractDraft(id=uuid.uuid4(), parcel_id=parcel.id, s3_key=key, version=1)
        db.add(cd)

        memo_payload = {"deal_memo_id": str(memo.id), "parcel_id": str(parcel.id), "title": title}
        contract_payload = {"contract_draft_id": str(cd.id), "parcel_id": str(parcel.id), "s3_key": key}

        pilot_deal = load_pilot_config(settings.pilot_config_path).deal
        auto_types: frozenset[str] = (
            frozenset({"deal_memo_publish"})
            if pilot_deal.auto_approve_deal_memo_publish
            else frozenset()
        )

        queue_approval(
            db,
            approval_type="deal_memo_publish",
            payload=memo_payload,
            auto_approve_types=auto_types,
        )
        queue_approval(
            db,
            approval_type="contract_send",
            payload=contract_payload,
        )

        run.status = WorkflowStatus.blocked.value
        run.current_step = WorkflowStep.awaiting_human.value
        db.add(run)
        db.commit()

        write_audit(
            db,
            actor="system",
            action="pipeline_completed",
            entity_type="workflow_run",
            entity_id=str(run.id),
            meta={"parcel_id": parcel_id, "step": run.current_step},
        )
        post_agent_event_to_slack(
            get_settings(),
            agent="Scoring & pipeline agent",
            detail=(
                f"Parcel `{parcel.apn}` — score *{score.total_score:.1f}*; "
                f"*Human-gate coordinator*: 2 pending approvals (deal memo + contract); "
                f"workflow `{run.status}`."
            ),
        )
        return {"workflow_run_id": str(run.id), "status": run.status}
    except Exception as exc:  # noqa: BLE001
        run.status = WorkflowStatus.failed.value
        run.error = str(exc)
        db.add(run)
        db.commit()
        err_preview = str(exc)[:800]
        post_agent_event_to_slack(
            get_settings(),
            agent="Scoring & pipeline agent",
            detail=f"Pipeline failed for parcel `{parcel_id}`: `{err_preview}`",
        )
        raise
    finally:
        db.close()


@celery.task(name="app.tasks.exploration_campaign_tick")
def exploration_campaign_tick() -> dict[str, Any]:
    """Daily WA exploration: ingest GeoJSON for counties assigned to this calendar day (7-day window)."""
    settings = get_settings()
    if not settings.exploration_campaign_enabled:
        return {"skipped": True, "reason": "exploration_campaign_disabled"}
    start = settings.exploration_campaign_start_date
    if start is None:
        logger.warning(
            "exploration_campaign_tick: set EXPLORATION_CAMPAIGN_START_DATE=YYYY-MM-DD in worker env",
        )
        return {"skipped": True, "reason": "missing_start_date"}

    camp = load_campaign_config(settings.exploration_campaign_config_path)
    duration = int(camp.get("duration_days") or 7)
    template = str(camp.get("geojson_path_template") or "/app/data/exploration/{county_fips}.geojson")
    max_pipe = int(camp.get("max_auto_pipeline_per_county") or 120)

    pilot = load_pilot_config(settings.pilot_config_path)
    counties = sorted(pilot.region.county_fips or [])
    if not counties:
        return {"skipped": True, "reason": "no_counties_in_pilot"}

    today = datetime.now(tz=UTC).date()
    day_ix = campaign_day_index(start, today, duration)
    if day_ix is None:
        return {
            "skipped": True,
            "reason": "outside_campaign_window",
            "start": str(start),
            "duration_days": duration,
        }

    day_counties = counties_for_exploration_day(counties, day_ix)
    enqueued = 0
    missing: list[str] = []
    for fips in day_counties:
        geo_path = template.format(county_fips=fips)
        if not Path(geo_path).is_file():
            missing.append(fips)
            continue
        ingest_geojson_path.delay(
            geo_path,
            default_county_fips=fips,
            auto_run_pipeline=True,
            max_auto_pipeline=max_pipe,
            delete_after=False,
        )
        enqueued += 1

    logger.info(
        "exploration_campaign_tick day_index=%s counties_today=%s ingests_enqueued=%s missing_geojson=%s",
        day_ix,
        len(day_counties),
        enqueued,
        len(missing),
    )
    return {
        "skipped": False,
        "campaign_day_index": day_ix,
        "counties_scheduled_today": day_counties,
        "ingests_enqueued": enqueued,
        "missing_geojson_counties": missing,
    }


@celery.task(name="app.tasks.wa_statewide_rollout_tick")
def wa_statewide_rollout_tick() -> dict[str, Any]:
    """Daily: ingest the next WA county (zero rows in DB) from WaTech when the parking queue is not overloaded."""
    settings = get_settings()
    if not settings.wa_statewide_rollout_enabled:
        return {"skipped": True, "reason": "wa_statewide_rollout_disabled"}

    from app.load_governor import (
        current_governor_state,
        effective_wa_rollout_limits,
        governor_allows_wa_rollout,
        refresh_load_governor,
    )

    rollout = load_rollout_config(settings.wa_statewide_rollout_config_path)
    pacing = wa_rollout_pacing()
    merged = merge_rollout_config(rollout, pacing)
    max_queue = int(merged.get("max_parking_queue_depth") or 400)
    queue_depth = parking_queue_depth(settings.redis_url)
    governor = (
        refresh_load_governor(settings)
        if settings.load_governor_enabled
        else current_governor_state(settings)
    )
    if settings.load_governor_enabled:
        allowed, reason = governor_allows_wa_rollout(settings, governor)
        if not allowed:
            logger.info("wa_statewide_rollout_tick: load_governor — %s", reason)
            return {
                "skipped": True,
                "reason": "load_governor_blocked",
                "load_governor": governor,
            }
    if queue_depth > max_queue:
        logger.info(
            "wa_statewide_rollout_tick: parking queue=%s > max=%s — deferring new county ingest",
            queue_depth,
            max_queue,
        )
        return {
            "skipped": True,
            "reason": "parking_queue_busy",
            "parking_queue_depth": queue_depth,
            "max_parking_queue_depth": max_queue,
        }

    db = _session()
    try:
        pending = wa_rollout_pending_ingest_state(db, merged)
        if pending.get("pending"):
            return {
                "skipped": True,
                "reason": "wa_rollout_pending_ingest",
                "pending_county_fips": pending.get("pending_county_fips"),
                "pending_age_days": pending.get("pending_age_days"),
                "pending_lock_days": pending.get("pending_lock_days"),
            }

        cooldown = wa_rollout_cooldown_state(db, merged)
        if not cooldown.get("ready"):
            return {
                "skipped": True,
                "reason": "wa_rollout_cooldown",
                "required_cooldown_days": cooldown.get("required_cooldown_days"),
                "days_since_last_county_ingest": cooldown.get("days_since_last_ingest"),
                "last_county_fips": cooldown.get("last_county_fips"),
                "last_county_parcels_in_db": cooldown.get("last_county_parcels_in_db"),
            }

        county = next_county_to_ingest(
            db,
            config=rollout,
            pilot_config_path=settings.pilot_config_path,
        )
        if county is None:
            return {"skipped": True, "reason": "all_priority_counties_have_parcels"}

        max_feat = rollout.get("watech_max_features")
        max_features: int | None
        if max_feat is None or max_feat == "":
            max_features = None
        else:
            max_features = int(max_feat)

        max_pipe = int(merged.get("max_auto_pipeline") or 15)
        if settings.load_governor_enabled:
            _, max_pipe = effective_wa_rollout_limits(
                settings,
                base_min_days=float(merged.get("min_days_between_counties") or 4),
                base_max_auto_pipeline=max_pipe,
                state=governor,
            )
        write_audit(
            db,
            actor="celery:wa_statewide_rollout",
            action="wa_statewide_county_ingest",
            entity_type="county_fips",
            entity_id=county,
            meta={"max_auto_pipeline": max_pipe, "parking_queue_depth": queue_depth},
        )
        db.commit()
        post_agent_event_to_slack(
            settings,
            agent="Statewide ingest",
            detail=(
                f"Starting WaTech ingest for county `{county}` "
                f"(pipeline cap {max_pipe}/parcel batch; queue depth {queue_depth}; "
                "next county after size-based cooldown)."
            ),
        )
        ar = fetch_watech_county_and_ingest.delay(
            county,
            max_features=max_features,
            auto_run_pipeline=True,
            max_auto_pipeline=max_pipe,
        )
        return {
            "skipped": False,
            "county_fips": county,
            "fetch_task_id": ar.id,
            "max_features": max_features,
            "max_auto_pipeline": max_pipe,
            "parking_queue_depth": queue_depth,
        }
    finally:
        db.close()


@celery.task(name="app.tasks.fetch_baltimore_city_and_ingest")
def fetch_baltimore_city_and_ingest(
    max_features: int | None = None,
    auto_run_pipeline: bool = True,
    max_auto_pipeline: int = 100,
) -> dict[str, Any]:
    """Download Baltimore City EGIS parcels; write temp GeoJSON; enqueue ``ingest_geojson_path``."""
    import json
    import tempfile

    from parking_ingestion.baltimore_parcels import BALTIMORE_CITY_COUNTY_FIPS, fetch_baltimore_city_geojson

    collection = fetch_baltimore_city_geojson(max_features=max_features)
    nfeat = len(collection.get("features", []))
    if nfeat == 0:
        return {"skipped": True, "reason": "no_features", "county_fips": BALTIMORE_CITY_COUNTY_FIPS}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".geojson", delete=False) as tmp:
        json.dump(collection, tmp)
        path = tmp.name

    ar = ingest_geojson_path.delay(
        path,
        default_county_fips=BALTIMORE_CITY_COUNTY_FIPS,
        delete_after=True,
        auto_run_pipeline=auto_run_pipeline,
        max_auto_pipeline=max_auto_pipeline,
    )
    return {
        "county_fips": BALTIMORE_CITY_COUNTY_FIPS,
        "features": nfeat,
        "ingest_task_id": ar.id,
        "geojson_path": path,
    }


@celery.task(name="app.tasks.fetch_baltimore_county_and_ingest")
def fetch_baltimore_county_and_ingest(
    max_features: int | None = 5000,
    auto_run_pipeline: bool = True,
    max_auto_pipeline: int = 100,
) -> dict[str, Any]:
    """Download Baltimore County tax parcels; write temp GeoJSON; enqueue ``ingest_geojson_path``."""
    import json
    import tempfile

    from parking_ingestion.baltimore_parcels import BALTIMORE_COUNTY_COUNTY_FIPS, fetch_baltimore_county_geojson

    collection = fetch_baltimore_county_geojson(max_features=max_features)
    nfeat = len(collection.get("features", []))
    if nfeat == 0:
        return {"skipped": True, "reason": "no_features", "county_fips": BALTIMORE_COUNTY_COUNTY_FIPS}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".geojson", delete=False) as tmp:
        json.dump(collection, tmp)
        path = tmp.name

    ar = ingest_geojson_path.delay(
        path,
        default_county_fips=BALTIMORE_COUNTY_COUNTY_FIPS,
        delete_after=True,
        auto_run_pipeline=auto_run_pipeline,
        max_auto_pipeline=max_auto_pipeline,
    )
    return {
        "county_fips": BALTIMORE_COUNTY_COUNTY_FIPS,
        "features": nfeat,
        "ingest_task_id": ar.id,
        "geojson_path": path,
    }


@celery.task(name="app.tasks.fetch_watech_county_and_ingest")
def fetch_watech_county_and_ingest(
    county_fips: str,
    max_features: int | None = 5000,
    auto_run_pipeline: bool = True,
    max_auto_pipeline: int = 100,
) -> dict[str, Any]:
    """Download WaTech public parcel polygons for one county; write temp GeoJSON; enqueue ``ingest_geojson_path``."""
    import json
    import tempfile

    from parking_ingestion.watech_parcels import fetch_county_geojson

    collection = fetch_county_geojson(county_fips, max_features=max_features)
    nfeat = len(collection.get("features", []))
    if nfeat == 0:
        return {
            "county_fips": county_fips,
            "parcel_features": 0,
            "ingest_task_id": None,
            "warning": "no features returned (check county FIPS or layer availability)",
        }

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".geojson",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        json.dump(collection, tmp)
        tmp_path = tmp.name

    ar = ingest_geojson_path.delay(
        tmp_path,
        default_county_fips=county_fips,
        auto_run_pipeline=auto_run_pipeline,
        max_auto_pipeline=max_auto_pipeline,
        delete_after=True,
    )
    return {
        "county_fips": county_fips,
        "parcel_features": nfeat,
        "ingest_task_id": ar.id,
        "max_features_cap": max_features,
    }


def _governed_pipeline_limit(requested: int) -> tuple[int, dict[str, Any] | None]:
    settings = get_settings()
    if not settings.load_governor_enabled:
        return requested, None
    from app.load_governor import current_governor_state, effective_pipeline_limit, refresh_load_governor

    governor = current_governor_state(settings)
    if not governor.get("assessed_at"):
        governor = refresh_load_governor(settings)
    cap = effective_pipeline_limit(requested, settings, governor)
    return cap, governor


@celery.task(name="app.tasks.enqueue_priority_qualified_scheduled")
def enqueue_priority_qualified_scheduled(limit: int = 75) -> dict[str, Any]:
    """Beat: drain prescreen-qualified backlog starting with highest entitlement scores."""
    cap, governor = _governed_pipeline_limit(limit)
    if cap <= 0:
        return {
            "enqueued": 0,
            "parcel_ids": [],
            "skipped": True,
            "reason": "load_governor_paused_pipeline_enqueue",
            "load_governor": governor,
        }
    out = enqueue_priority_qualified_pipeline_jobs(cap)
    if governor:
        out["load_governor"] = governor
    if out["enqueued"]:
        logger.info(
            "enqueue_priority_qualified_scheduled: enqueued %s pipeline(s) (cap=%s)",
            out["enqueued"],
            cap,
        )
    return out


@celery.task(name="app.tasks.enqueue_unscored_pipelines_scheduled")
def enqueue_unscored_pipelines_scheduled(limit: int = 100) -> dict[str, Any]:
    """Beat: enqueue ``run_pipeline`` for parcels missing entitlement **or** strategic scores."""
    cap, governor = _governed_pipeline_limit(limit)
    if cap <= 0:
        return {
            "enqueued": 0,
            "parcel_ids": [],
            "skipped": True,
            "reason": "load_governor_paused_pipeline_enqueue",
            "load_governor": governor,
        }
    out = enqueue_incomplete_pipeline_jobs(cap)
    if governor:
        out["load_governor"] = governor
    if out["enqueued"]:
        logger.info(
            "enqueue_unscored_pipelines_scheduled: enqueued %s incomplete pipeline(s) (cap=%s)",
            out["enqueued"],
            cap,
        )
    return out


@celery.task(name="app.tasks.load_governor_refresh")
def load_governor_refresh() -> dict[str, Any]:
    """Periodic: refresh load governor from queue/workers + cached ops snapshot."""
    settings = get_settings()
    if not settings.load_governor_enabled:
        return {"skipped": True, "reason": "load_governor_disabled"}
    from app.load_governor import refresh_load_governor

    return refresh_load_governor(settings)


@celery.task(name="app.tasks.ingest_geojson_path")
def ingest_geojson_path(
    path: str,
    default_county_fips: str | None = None,
    auto_run_pipeline: bool = False,
    max_auto_pipeline: int = 100,
    delete_after: bool = False,
) -> dict[str, Any]:
    """Load parcel polygons from GeoJSON; upsert by (county_fips, apn); optionally enqueue scoring pipelines."""
    from parking_ingestion.geojson_loader import iter_parcels_from_geojson_dict, load_geojson_path
    from parking_ingestion.parcel_metrics import geodesic_footprint_sqft, min_distance_to_generators_m

    data = load_geojson_path(Path(path))
    db = _session()
    ids: list[str] = []
    inserted = 0
    updated = 0
    skipped = 0
    county_touches: dict[str, int] = {}
    try:
        pilot = load_pilot_config(get_settings().pilot_config_path)
        zrp = (get_settings().zoning_rules_path or "").strip()
        zoning_rules_arg = Path(zrp) if zrp else None
        for attrs, geom in iter_parcels_from_geojson_dict(data, rules_path=zoning_rules_arg):
            if geom.geom_type not in ("Polygon", "MultiPolygon"):
                skipped += 1
                continue
            multi = _to_multi(geom)  # type: ignore[arg-type]
            county = str(attrs["county_fips"] or "").strip() or (default_county_fips or "").strip()
            apn = str(attrs["apn"] or "").strip()
            if not apn:
                skipped += 1
                continue
            if pilot.region.county_fips and county not in pilot.region.county_fips:
                skipped += 1
                continue

            lot_sqft = float(attrs["lot_sqft"]) if attrs.get("lot_sqft") is not None else None
            if lot_sqft is None:
                est = geodesic_footprint_sqft(multi)
                if est is not None:
                    lot_sqft = est

            distance_m: float | None = None
            if attrs.get("distance_to_nearest_demand_m") is not None:
                distance_m = float(attrs["distance_to_nearest_demand_m"])
            elif pilot.scoring.demand_generators:
                c = multi.centroid
                dmin = min_distance_to_generators_m(c.y, c.x, pilot.scoring.demand_generators)
                if dmin is not None:
                    distance_m = dmin

            footprint = WKTElement(multi.wkt, srid=4326)
            existing = db.scalars(
                select(Parcel).where(Parcel.county_fips == county, Parcel.apn == apn).limit(1)
            ).first()
            zoning_code = str(attrs["zoning_code"]) if attrs.get("zoning_code") else None
            if existing is None:
                p = Parcel(
                    id=uuid.uuid4(),
                    apn=apn,
                    county_fips=county,
                    lot_sqft=lot_sqft,
                    zoning_code=zoning_code,
                    zoning_allows_surface_parking=bool(attrs.get("zoning_allows_surface_parking")),
                    is_corner_lot=bool(attrs.get("is_corner_lot")),
                    distance_to_nearest_demand_m=distance_m,
                    raw_properties=attrs.get("raw_properties") or {},
                    footprint=footprint,
                )
                db.add(p)
                db.flush()
                _upsert_identification_score(db, p)
                pid = str(p.id)
                inserted += 1
            else:
                db.execute(
                    delete(ParcelScore).where(
                        ParcelScore.parcel_id == existing.id,
                        ParcelScore.score_profile.in_(PIPELINE_PROFILES),
                    )
                )
                existing.lot_sqft = lot_sqft
                existing.zoning_code = zoning_code
                existing.zoning_allows_surface_parking = bool(attrs.get("zoning_allows_surface_parking"))
                existing.is_corner_lot = bool(attrs.get("is_corner_lot"))
                existing.distance_to_nearest_demand_m = distance_m
                existing.raw_properties = attrs.get("raw_properties") or {}
                existing.footprint = footprint
                db.add(existing)
                db.flush()
                _upsert_identification_score(db, existing)
                pid = str(existing.id)
                updated += 1
            county_touches[county] = county_touches.get(county, 0) + 1
            ids.append(pid)
        db.commit()
        write_audit(
            db,
            actor="system",
            action="parcels_ingested",
            entity_type="parcel",
            entity_id=None,
            meta={
                "parcel_ids": ids,
                "source_path": path,
                "default_county_fips": (default_county_fips or "").strip() or None,
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "county_touches": county_touches,
                "auto_run_pipeline": auto_run_pipeline,
            },
        )
        zoning_followups = _record_wa_zoning_followups_after_ingest(
            db,
            county_touches=county_touches,
            source_path=path,
        )
        pipelines_enqueued = 0
        if auto_run_pipeline and ids:
            qualified = filter_prescreen_qualified_ids(db, ids)
            pipelines_enqueued = min(len(qualified), max(0, max_auto_pipeline))
            for pid in qualified[: max(0, max_auto_pipeline)]:
                run_pipeline.delay(pid)
            if len(qualified) > max_auto_pipeline:
                logger.warning(
                    "ingest_geojson_path: auto_run_pipeline capped at %s of %s prescreen-qualified parcels",
                    max_auto_pipeline,
                    len(qualified),
                )
            if len(ids) > len(qualified):
                logger.info(
                    "ingest_geojson_path: skipped pipeline for %s parcels below prescreen floor",
                    len(ids) - len(qualified),
                )
        label = Path(path).name
        county = (default_county_fips or "").strip()
        from app.pilot_scope import COUNTY_DISPLAY_NAMES

        county_line = ""
        if county:
            cname = COUNTY_DISPLAY_NAMES.get(county, county)
            county_line = f"*Market:* {cname} (`{county}`)\n"
        ingest_detail = (
            f"{county_line}"
            f"*File:* `{label}`\n"
            f"• Inserted (new APNs): *{inserted}* · Refreshed existing: *{updated}* · Skipped: *{skipped}*\n"
            "_Refreshed rows do not change `parcels.created_at` (hourly digest “new parcel rows”)._"
        )
        if pipelines_enqueued:
            ingest_detail += f"\n• Scoring pipelines enqueued: *{pipelines_enqueued}* (prescreen-qualified)."
        if zoning_followups:
            ingest_detail += (
                f"\n• Zoning follow-up opened for *{len(zoning_followups)}* WA county/counties "
                "(source discovery / layer join / QA)."
            )
        post_agent_event_to_slack(get_settings(), agent="Ingest agent", detail=ingest_detail)
        return {
            "parcel_ids": ids,
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "pipelines_enqueued": pipelines_enqueued,
            "zoning_followup_required": len(zoning_followups),
            "zoning_followup_counties": [str(row["county_fips"]) for row in zoning_followups],
        }
    finally:
        db.close()
        if delete_after:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                logger.warning("ingest_geojson_path: could not delete temp file %s", path)


@celery.task(name="app.tasks.merge_parcel_attributes_geojson")
def merge_parcel_attributes_geojson(
    path: str,
    default_county_fips: str | None = None,
    delete_after: bool = False,
    refresh_pipeline: bool = True,
    max_pipeline: int = 100,
) -> dict[str, Any]:
    """Update existing parcels from a GeoJSON overlay (zoning, corner, demand distance, lot_sqft).

    Does **not** insert new parcels. Use after spatial joins or assessor enrichments land in GeoJSON
    properties (``ZONING``, ``ZONING_JURISDICTION``, ``IS_CORNER``, ``DIST_DEMAND_M``, etc.).
    """
    from parking_ingestion.geojson_loader import iter_parcels_from_geojson_dict, load_geojson_path

    data = load_geojson_path(Path(path))
    db = _session()
    zrp = (get_settings().zoning_rules_path or "").strip()
    zoning_rules_arg = Path(zrp) if zrp else None
    pilot = load_pilot_config(get_settings().pilot_config_path)
    updated = 0
    skipped_region = 0
    not_found = 0
    pipeline_ids: list[str] = []
    try:
        for attrs, _geom in iter_parcels_from_geojson_dict(data, rules_path=zoning_rules_arg):
            county = str(attrs["county_fips"] or "").strip() or (default_county_fips or "").strip()
            apn = str(attrs["apn"] or "").strip()
            if not apn or not county:
                continue
            if pilot.region.county_fips and county not in pilot.region.county_fips:
                skipped_region += 1
                continue
            row = db.scalars(
                select(Parcel).where(Parcel.county_fips == county, Parcel.apn == apn).limit(1)
            ).first()
            if row is None:
                not_found += 1
                continue
            if attrs.get("zoning_code") is not None:
                row.zoning_code = str(attrs["zoning_code"])
            row.zoning_allows_surface_parking = bool(attrs.get("zoning_allows_surface_parking"))
            row.is_corner_lot = bool(attrs.get("is_corner_lot"))
            if attrs.get("distance_to_nearest_demand_m") is not None:
                row.distance_to_nearest_demand_m = float(attrs["distance_to_nearest_demand_m"])
            if attrs.get("lot_sqft") is not None:
                row.lot_sqft = float(attrs["lot_sqft"])
            overlay = attrs.get("raw_properties") or {}
            if isinstance(overlay, dict) and overlay:
                merged = dict(row.raw_properties or {})
                merged.update({k: v for k, v in overlay.items() if v is not None})
                row.raw_properties = merged
            db.add(row)
            db.flush()
            _upsert_identification_score(db, row)
            _upsert_entitlement_score(db, row)
            updated += 1
            pipeline_ids.append(str(row.id))
        db.commit()
        write_audit(
            db,
            actor="system",
            action="parcels_merge_attributes",
            entity_type="parcel",
            entity_id=None,
            meta={
                "source_path": path,
                "updated": updated,
                "not_found": not_found,
                "skipped_region": skipped_region,
            },
        )
        cap = min(max(max_pipeline, 0), 5000)
        enq = 0
        if refresh_pipeline and pipeline_ids and cap > 0:
            qualified = filter_prescreen_qualified_ids(db, pipeline_ids)
            for pid in qualified[:cap]:
                run_pipeline.delay(pid)
                enq += 1
            if len(pipeline_ids) > len(qualified):
                logger.info(
                    "merge_parcel_attributes_geojson: skipped pipeline for %s parcels below prescreen floor",
                    len(pipeline_ids) - len(qualified),
                )
        post_agent_event_to_slack(
            get_settings(),
            agent="Cartographer (attribute merge)",
            detail=(
                f"Merged GeoJSON overlay `{Path(path).name}` — updated *{updated}*, "
                f"no row *{not_found}*, skipped pilot *{skipped_region}*; pipelines *{enq}*."
            ),
        )
        return {
            "updated": updated,
            "not_found": not_found,
            "skipped_wrong_region": skipped_region,
            "pipelines_enqueued": enq,
            "parcel_ids": pipeline_ids[:20],
        }
    finally:
        db.close()
        if delete_after:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                logger.warning("merge_parcel_attributes_geojson: could not delete temp file %s", path)


@celery.task(name="app.tasks.refresh_demand_distances_batch")
def refresh_demand_distances_batch(
    limit: int = 500,
    county_fips: str | None = None,
    process_all: bool = False,
    refresh_identification: bool = True,
) -> dict[str, Any]:
    """Recompute ``distance_to_nearest_demand_m`` from pilot.yaml demand generators (centroid → POI)."""
    from geoalchemy2.shape import to_shape

    from parking_ingestion.parcel_metrics import min_distance_to_generators_m

    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    if not pilot.scoring.demand_generators:
        return {"skipped": True, "reason": "no_demand_generators_in_pilot", "updated": 0}

    chunk = min(max(limit, 1), 5000)
    cf = (county_fips or "").strip()
    db = _session()
    n = 0
    last_id: uuid.UUID | None = None
    try:
        while True:
            stmt = select(Parcel).where(Parcel.footprint.isnot(None))
            if cf:
                stmt = stmt.where(Parcel.county_fips == cf)
            if last_id is not None:
                stmt = stmt.where(Parcel.id > last_id)
            stmt = stmt.order_by(Parcel.id.asc()).limit(chunk)
            batch = list(db.scalars(stmt))
            if not batch:
                break
            for parcel in batch:
                last_id = parcel.id
                geom = to_shape(parcel.footprint)
                if geom.is_empty:
                    continue
                c = geom.centroid
                dmin = min_distance_to_generators_m(c.y, c.x, pilot.scoring.demand_generators)
                try:
                    wrote = update_parcel_columns_if(
                        db,
                        parcel.id,
                        {"distance_to_nearest_demand_m": dmin},
                    )
                except OperationalError:
                    db.rollback()
                    continue
                if not wrote:
                    continue
                n += 1
                if refresh_identification:
                    try:
                        parcel.distance_to_nearest_demand_m = dmin
                        _upsert_identification_score(db, parcel)
                        db.commit()
                    except OperationalError:
                        db.rollback()
            if not process_all or len(batch) < chunk:
                break
        post_agent_event_to_slack(
            settings,
            agent="Beacon (demand distance refresh)",
            detail=f"Refreshed demand distance for *{n}* parcel(s)" + (f" in `{cf}`." if cf else "."),
        )
        return {
            "updated": n,
            "county_fips": cf or None,
            "limit": chunk,
            "process_all": process_all,
            "refresh_identification": refresh_identification,
            "generator_count": len(pilot.scoring.demand_generators),
        }
    finally:
        db.close()


@celery.task(name="app.tasks.refresh_poi_density_batch")
def refresh_poi_density_batch(
    limit: int = 50,
    county_fips: str | None = None,
    only_missing: bool = True,
    process_all: bool = False,
) -> dict[str, Any]:
    """Count commercial OSM POIs near each parcel centroid (Overpass API, rate-limited).

    Uses short per-parcel commits and conditional UPDATE so batch jobs can run alongside
    live Celery workers without requiring a quiet Droplet.
    """
    from geoalchemy2.shape import to_shape

    from app.db.schema_compat import column_exists
    from parking_ingestion.osm_poi import count_commercial_pois_osm_throttled

    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    poi_cfg = pilot.scoring.poi_demand
    radius_m = int(poi_cfg.radius_m) if poi_cfg is not None else 400

    chunk = min(max(limit, 1), 200)
    cf = (county_fips or "").strip()
    db = _session()
    if not column_exists(db, "parcels", "poi_commercial_count_400m"):
        db.close()
        return {
            "skipped": True,
            "reason": "poi_commercial_count_400m column missing — run alembic upgrade",
            "updated": 0,
        }

    n = 0
    skipped = 0
    errors = 0
    last_at: float | None = None
    attempted_ids: set[uuid.UUID] = set()
    try:
        while True:
            stmt = select_poi_density_candidates(
                limit=chunk,
                county_fips=cf,
                only_missing=only_missing,
                exclude_ids=attempted_ids,
            )
            batch = list(db.scalars(stmt))
            if not batch:
                break

            for parcel in batch:
                attempted_ids.add(parcel.id)
                geom = to_shape(parcel.footprint)
                if geom.is_empty:
                    continue
                c = geom.centroid
                try:
                    count, last_at = count_commercial_pois_osm_throttled(
                        c.y,
                        c.x,
                        radius_m=radius_m,
                        overpass_url=settings.poi_overpass_url,
                        user_agent=settings.poi_overpass_user_agent,
                        delay_sec=settings.poi_overpass_delay_sec,
                        last_request_at=last_at,
                    )
                except RuntimeError:
                    errors += 1
                    continue

                where_extra = (Parcel.poi_commercial_count_400m.is_(None),) if only_missing else ()
                try:
                    wrote = update_parcel_columns_if(
                        db,
                        parcel.id,
                        {"poi_commercial_count_400m": count},
                        *where_extra,
                    )
                except OperationalError:
                    db.rollback()
                    errors += 1
                    continue
                if wrote:
                    n += 1
                else:
                    skipped += 1

            if not process_all or len(batch) < chunk:
                break

        if n:
            post_agent_event_to_slack(
                settings,
                agent="Beacon (POI density refresh)",
                detail=f"Updated OSM commercial POI count for *{n}* parcel(s)"
                + (f" in `{cf}`." if cf else ".")
                + (f" ({errors} Overpass error(s).)" if errors else ""),
            )
        return {
            "updated": n,
            "skipped_already_set": skipped,
            "errors": errors,
            "county_fips": cf or None,
            "limit": chunk,
            "radius_m": radius_m,
            "only_missing": only_missing,
            "process_all": process_all,
            "candidate_mode": POI_DENSITY_CANDIDATE_MODE,
            "entitlement_floor": entitlement_qualified_floor(),
            "strategic_floor": strategic_qualified_floor(),
        }
    finally:
        db.close()


@celery.task(name="app.tasks.refresh_pipeline_scores_with_rate_comps_batch")
def refresh_pipeline_scores_with_rate_comps_batch(
    limit: int = 500,
    county_fips: str | None = None,
    min_entitlement_score: float | None = None,
) -> dict[str, Any]:
    """Recompute Atlas/Beacon scores with nearby paid parking comps (footprint required)."""
    settings = get_settings()
    pilot_ent = load_pilot_config(settings.pilot_config_path)
    pilot_str = load_pilot_config(settings.pilot_strategic_config_path)
    floor = (
        float(min_entitlement_score)
        if min_entitlement_score is not None
        else entitlement_qualified_floor()
    )
    lim = min(max(limit, 1), 5000)
    db = _session()
    n = 0
    try:
        ent_agg = (
            select(
                ParcelScore.parcel_id.label("pid"),
                func.max(ParcelScore.created_at).label("mx"),
            )
            .where(ParcelScore.score_profile == ENTITLEMENT)
            .group_by(ParcelScore.parcel_id)
            .subquery()
        )
        ent = (
            select(ParcelScore.parcel_id, ParcelScore.total_score.label("ent_score"))
            .join(
                ent_agg,
                and_(
                    ParcelScore.parcel_id == ent_agg.c.pid,
                    ParcelScore.created_at == ent_agg.c.mx,
                ),
            )
            .where(
                ParcelScore.score_profile == ENTITLEMENT,
                ParcelScore.total_score >= floor,
            )
            .subquery()
        )
        stmt = (
            select(Parcel, ent.c.ent_score)
            .join(ent, Parcel.id == ent.c.parcel_id)
            .where(Parcel.footprint.isnot(None))
            .order_by(desc(ent.c.ent_score))
            .limit(lim)
        )
        cf = (county_fips or "").strip()
        if cf:
            stmt = stmt.where(Parcel.county_fips == cf)
        for parcel, _prev in db.execute(stmt):
            score_ent = _score_parcel_with_nearby_comps(db, parcel=parcel, pilot=pilot_ent)
            _persist_pipeline_score(db, parcel_id=parcel.id, profile=ENTITLEMENT, result=score_ent)
            score_str = _score_parcel_with_nearby_comps(db, parcel=parcel, pilot=pilot_str)
            _persist_pipeline_score(db, parcel_id=parcel.id, profile=STRATEGIC, result=score_str)
            n += 1
            if n % 100 == 0:
                db.commit()
        db.commit()
        post_agent_event_to_slack(
            settings,
            agent="Atlas (rate-comp score refresh)",
            detail=(
                f"Re-scored *{n}* parcel(s) with nearby paid parking comps"
                + (f" in `{cf}`" if cf else "")
                + f" (entitlement ≥ *{floor:.0f}*)."
            ),
        )
        return {
            "updated": n,
            "county_fips": cf or None,
            "limit": lim,
            "min_entitlement_score": floor,
        }
    finally:
        db.close()


@celery.task(name="app.tasks.backfill_baltimore_property_addresses_batch")
def backfill_baltimore_property_addresses_batch(limit: int = 500, dry_run: bool = False) -> dict[str, Any]:
    """Measured Baltimore City address backfill batch from Realproperty_OB."""
    from app.baltimore_address_backfill import backfill_baltimore_property_addresses

    db = _session()
    try:
        return backfill_baltimore_property_addresses(db, limit=limit, dry_run=dry_run)
    finally:
        db.close()


@celery.task(name="app.tasks.backfill_wa_centroid_addresses_batch")
def backfill_wa_centroid_addresses_batch(
    limit: int = 100,
    county_fips: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """WA candidate situs backfill via Nominatim + assessor city/ZIP anchor."""
    from app.wa_centroid_address_backfill import backfill_wa_centroid_addresses

    db = _session()
    try:
        return backfill_wa_centroid_addresses(db, limit=limit, county_fips=county_fips, dry_run=dry_run)
    finally:
        db.close()


@celery.task(name="app.tasks.address_health_agent_tick")
def address_health_agent_tick() -> dict[str, Any]:
    """Every 12h: run address health review script (backup to GitHub Actions + Droplet cron)."""
    import json
    import subprocess
    import sys
    from pathlib import Path

    settings = get_settings()
    if not settings.address_health_agent_enabled:
        return {"skipped": True, "reason": "address_health_agent_disabled"}

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "address-health-agent" / "address_health_agent.py"
    if not script.is_file():
        return {"skipped": True, "reason": "script_missing", "path": str(script)}

    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--json"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.exception("address_health_agent_tick timed out")
        return {"skipped": False, "ok": False, "reason": "timeout"}

    if proc.returncode != 0:
        logger.warning(
            "address_health_agent_tick exit=%s stderr=%s",
            proc.returncode,
            (proc.stderr or "")[:500],
        )
        return {
            "skipped": False,
            "ok": False,
            "exit_code": proc.returncode,
            "stderr": (proc.stderr or "")[:2000],
        }

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        payload = {"raw_stdout": (proc.stdout or "")[:2000]}
    return {"skipped": False, "ok": True, "report": payload}


@celery.task(name="app.tasks.refresh_identification_scores_batch")
def refresh_identification_scores_batch(
    limit: int = 2000,
    county_fips: str | None = None,
) -> dict[str, Any]:
    """Upsert ``identification`` scores for parcels that have no identification ``parcel_scores`` row."""
    lim = min(max(limit, 1), 5000)
    db = _session()
    n = 0
    try:
        miss_ident = ~exists(
            select(1).where(
                ParcelScore.parcel_id == Parcel.id,
                ParcelScore.score_profile == IDENTIFICATION,
            )
        )
        stmt = select(Parcel).where(miss_ident)
        cf = (county_fips or "").strip()
        if cf:
            stmt = stmt.where(Parcel.county_fips == cf)
        stmt = stmt.order_by(Parcel.created_at.desc()).limit(lim)
        for parcel in db.scalars(stmt):
            _upsert_identification_score(db, parcel)
            n += 1
            if n % 200 == 0:
                db.commit()
        db.commit()
        post_agent_event_to_slack(
            get_settings(),
            agent="Cartographer (identification refresh)",
            detail=f"Upserted identification score for *{n}* parcel(s)" + (f" in `{cf}`." if cf else "."),
        )
        return {"updated": n, "county_fips": cf or None, "limit": lim}
    finally:
        db.close()


@celery.task(name="app.tasks.refresh_entitlement_scores_batch")
def refresh_entitlement_scores_batch(
    limit: int = 2000,
    county_fips: str | None = None,
    process_all: bool = False,
    prescreen_qualified_only: bool = False,
) -> dict[str, Any]:
    """Recompute Atlas entitlement scores from current parcel features (zoning, lot, demand, comps)."""
    chunk = min(max(limit, 1), 5000)
    cf = (county_fips or "").strip()
    db = _session()
    n = 0
    last_id: uuid.UUID | None = None
    try:
        while True:
            stmt = select(Parcel)
            if cf:
                stmt = stmt.where(Parcel.county_fips == cf)
            if prescreen_qualified_only:
                stmt = stmt.where(identification_prescreen_qualified())
            if last_id is not None:
                stmt = stmt.where(Parcel.id > last_id)
            stmt = stmt.order_by(Parcel.id.asc()).limit(chunk)
            batch = list(db.scalars(stmt))
            if not batch:
                break
            for parcel in batch:
                _upsert_entitlement_score(db, parcel)
                n += 1
                last_id = parcel.id
            db.commit()
            if not process_all or len(batch) < chunk:
                break
        post_agent_event_to_slack(
            get_settings(),
            agent="Atlas (entitlement refresh)",
            detail=f"Refreshed entitlement score for *{n}* parcel(s)" + (f" in `{cf}`." if cf else "."),
        )
        return {
            "updated": n,
            "county_fips": cf or None,
            "limit": chunk,
            "process_all": process_all,
            "prescreen_qualified_only": prescreen_qualified_only,
        }
    finally:
        db.close()


@celery.task(name="app.tasks.slack_qualified_parcels_report")
def slack_qualified_parcels_report() -> dict[str, Any]:
    """Post Block Kit summary of qualified vs not-qualified parcels (latest scores + rationale)."""
    settings = get_settings()
    token = (settings.slack_bot_token or "").strip()
    channel = (settings.slack_digest_channel_id or "").strip()
    if not token or not channel:
        logger.warning(
            "slack_qualified_parcels_report SKIPPED: missing SLACK_BOT_TOKEN or SLACK_DIGEST_CHANNEL_ID",
        )
        return {"skipped": True, "reason": "slack not configured"}
    db = _session()
    try:
        blocks, fallback = build_qualified_parcels_report_blocks(db, settings=settings)
        posted = post_digest_to_slack(settings, blocks, fallback)
        return {"skipped": False, **posted}
    except Exception:
        logger.exception("slack_qualified_parcels_report failed")
        raise
    finally:
        db.close()


@celery.task(name="app.tasks.slack_plan_progress_report")
def slack_plan_progress_report() -> dict[str, Any]:
    """Post hourly A-E plan progress to the same channel as the regular Slack updates."""
    settings = get_settings()
    token = (settings.slack_bot_token or "").strip()
    channel = (settings.slack_digest_channel_id or "").strip()
    if not token or not channel:
        logger.warning(
            "slack_plan_progress_report SKIPPED: missing SLACK_BOT_TOKEN or SLACK_DIGEST_CHANNEL_ID",
        )
        return {"skipped": True, "reason": "slack not configured"}
    db = _session()
    try:
        blocks, fallback = build_plan_progress_report_blocks(db)
        posted = post_digest_to_slack(settings, blocks, fallback)
        return {"skipped": False, **posted}
    except Exception:
        logger.exception("slack_plan_progress_report failed")
        raise
    finally:
        db.close()


@celery.task(name="app.tasks.slack_dual_agent_discussion")
def slack_dual_agent_discussion() -> dict[str, Any]:
    """Post 3 sequential messages to SLACK_AGENT_DISCUSSION_CHANNEL_ID (Atlas, Beacon, joint)."""
    settings = get_settings()
    token = (settings.slack_bot_token or "").strip()
    channel = (settings.slack_agent_discussion_channel_id or "").strip()
    if not token or not channel:
        logger.warning(
            "slack_dual_agent_discussion SKIPPED: missing SLACK_BOT_TOKEN or SLACK_AGENT_DISCUSSION_CHANNEL_ID",
        )
        return {"skipped": True, "reason": "slack agent channel not configured"}
    db = _session()
    try:
        posts = build_dual_agent_discussion_posts(db, settings=settings)
        out: list[dict[str, Any]] = []
        for blocks, fallback in posts:
            out.append(
                post_blocks_to_slack_channel(
                    settings,
                    channel_id=channel,
                    blocks=blocks,
                    fallback=fallback,
                )
            )
        return {"skipped": False, "message_count": len(out), "posts": out}
    except Exception:
        logger.exception("slack_dual_agent_discussion failed")
        raise
    finally:
        db.close()


@celery.task(name="app.tasks.slack_agent_digest")
def slack_agent_digest() -> dict[str, Any]:
    """Scheduled standup: post a Block Kit digest to Slack (worker executes; Beat only schedules)."""
    settings = get_settings()
    token = (settings.slack_bot_token or "").strip()
    channel = (settings.slack_digest_channel_id or "").strip()
    if not token or not channel:
        logger.warning(
            "slack_agent_digest SKIPPED: worker missing SLACK_BOT_TOKEN and/or SLACK_DIGEST_CHANNEL_ID "
            "(digest no-ops until both are set; restart worker + beat after updating deploy/.env). "
            "has_token=%s has_channel=%s",
            bool(token),
            bool(channel),
        )
        return {"skipped": True, "reason": "slack not configured (set SLACK_BOT_TOKEN and SLACK_DIGEST_CHANNEL_ID)"}
    db = _session()
    try:
        window_h = max(1, int(settings.slack_digest_window_hours or 1))
        blocks, fallback = build_slack_digest_blocks(db, hours=window_h, settings=settings)
        posted = post_digest_to_slack(settings, blocks, fallback)
        _write_slack_digest_audit(channel=channel, posted=posted, fallback=fallback)
        return {"skipped": False, **posted}
    except Exception:
        logger.exception("slack_agent_digest failed")
        raise
    finally:
        db.rollback()
        db.close()


@celery.task(name="app.tasks.ops_remediation_loop")
def ops_remediation_loop() -> dict[str, Any]:
    """Detect ops/data issues and enqueue remediations (Slack queue, Beat-scheduled)."""
    from app.ops_remediation import run_ops_remediation_loop

    settings = get_settings()
    if not settings.ops_remediation_enabled:
        return {"skipped": True, "reason": "ops_remediation_disabled"}

    db = _session()
    try:
        return run_ops_remediation_loop(db)
    except Exception:
        logger.exception("ops_remediation_loop failed")
        raise
    finally:
        db.close()


@celery.task(name="app.tasks.site_watchdog_check")
def site_watchdog_check() -> dict[str, Any]:
    """Check API, operator UI, Postgres, Redis/queues; alert Slack on failure or recovery."""
    from app.site_watchdog import (
        build_slack_text,
        load_last_report,
        run_droplet_watchdog,
        should_post_slack,
        watchdog_slack_channel,
    )

    settings = get_settings()
    token = (settings.slack_bot_token or "").strip()
    channel = watchdog_slack_channel(settings)
    slack_configured = bool(token and channel)
    if not slack_configured:
        logger.warning(
            "site_watchdog_check: Slack alerting disabled because SLACK_BOT_TOKEN or watchdog channel is missing "
            "(SITE_WATCHDOG_SLACK_CHANNEL_ID / SLACK_AGENT_DISCUSSION_CHANNEL_ID / SLACK_DIGEST_CHANNEL_ID)",
        )

    db = _session()
    try:
        previous = load_last_report(settings)
        report = run_droplet_watchdog(db)
        post, recovered = should_post_slack(settings, report, previous)
        result: dict[str, Any] = {
            "skipped": False,
            "ok": report.get("ok"),
            "posted": False,
            "slack_configured": slack_configured,
        }
        if slack_configured and post:
            text = build_slack_text(report, recovered=recovered)
            post_text_to_slack(settings, text=text, channel_id=str(channel))
            write_audit(
                db,
                actor="celery:site_watchdog",
                action="site_watchdog_alert" if not report.get("ok") else "site_watchdog_ok",
                entity_type="slack_channel",
                entity_id=str(channel),
                meta={"ok": report.get("ok"), "failure_count": report.get("failure_count"), "recovered": recovered},
            )
            result["posted"] = True
        return result
    except Exception:
        logger.exception("site_watchdog_check failed")
        raise
    finally:
        db.close()
