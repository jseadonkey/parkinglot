from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geoalchemy2.elements import WKTElement
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import delete, exists, not_, or_, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.celery_app import celery
from app.config import get_settings
from app.contract_render import render_ground_lease_draft
from app.db.models import ApprovalRequest, ContractDraft, DealMemo, OwnerCandidateRow, Parcel, ParcelScore, WorkflowRun
from app.db.session import SessionLocal
from app.exploration_campaign import (
    campaign_day_index,
    counties_for_exploration_day,
    load_campaign_config,
)
from app.memo_render import build_deal_memo_markdown
from app.outreach_contacts import sync_contact_points_from_brief
from app.owner_portfolio import count_qualified_peer_parcels
from app.scoring_profiles import (
    ENTITLEMENT,
    IDENTIFICATION,
    PIPELINE_PROFILES,
    STRATEGIC,
)
from app.slack_digest import (
    build_dual_agent_discussion_posts,
    build_qualified_parcels_report_blocks,
    build_slack_digest_blocks,
    post_agent_event_to_slack,
    post_blocks_to_slack_channel,
    post_digest_to_slack,
)
from app.storage import put_text_object
from parking_core.models import OwnerCandidate, ParcelFeature
from parking_core.pilot import load_pilot_config
from parking_enrichment.owner_normalize import scoped_owner_key
from parking_enrichment.owner_outreach_agent import build_owner_outreach_brief
from parking_enrichment.pipeline import enrich_from_parcel_row
from parking_enrichment.registry_lookup import lookup_secretary_of_state_stub
from parking_enrichment.vendor_lookup_client import fetch_vendor_owner_enrichment
from parking_scoring.engine import score_parcel
from parking_workflows.state import WorkflowStatus, WorkflowStep

logger = logging.getLogger(__name__)


def enqueue_unscored_pipeline_jobs(limit: int = 100) -> dict[str, Any]:
    """Enqueue ``run_pipeline`` for parcels missing an **entitlement** score row.

    Parcels may already have an ingest-time ``identification`` score; missing **strategic**
    alone does **not** match — use ``enqueue_incomplete_pipeline_jobs`` for that.

    Used by ``POST /internal/pipeline/enqueue-unscored`` and periodic Beat.
    """
    cap = min(max(limit, 1), 500)
    db = _session()
    try:
        stmt = (
            select(Parcel.id)
            .where(
                ~exists(
                    select(1).where(
                        ParcelScore.parcel_id == Parcel.id,
                        ParcelScore.score_profile == ENTITLEMENT,
                    )
                )
            )
            .order_by(Parcel.created_at.desc())
            .limit(cap)
        )
        ids = [str(i) for i in db.scalars(stmt)]
        for pid in ids:
            run_pipeline.delay(pid)
        return {"enqueued": len(ids), "parcel_ids": ids}
    finally:
        db.close()


def enqueue_incomplete_pipeline_jobs(limit: int = 100) -> dict[str, Any]:
    """Enqueue ``run_pipeline`` when entitlement **or** strategic score is missing."""
    cap = min(max(limit, 1), 500)
    db = _session()
    try:
        has_ent = exists(
            select(1).where(
                ParcelScore.parcel_id == Parcel.id,
                ParcelScore.score_profile == ENTITLEMENT,
            )
        )
        has_str = exists(
            select(1).where(
                ParcelScore.parcel_id == Parcel.id,
                ParcelScore.score_profile == STRATEGIC,
            )
        )
        stmt = (
            select(Parcel.id)
            .where(or_(not_(has_ent), not_(has_str)))
            .order_by(Parcel.created_at.desc())
            .limit(cap)
        )
        ids = [str(i) for i in db.scalars(stmt)]
        for pid in ids:
            run_pipeline.delay(pid)
        return {"enqueued": len(ids), "parcel_ids": ids, "mode": "missing_entitlement_or_strategic"}
    finally:
        db.close()


def _session() -> Session:
    return SessionLocal()


def _upsert_identification_score(db: Session, parcel: Parcel) -> None:
    """Persist ingest-time prescreen score (``identification`` profile)."""
    settings = get_settings()
    pilot_id = load_pilot_config(settings.pilot_identification_config_path)
    feature = ParcelFeature(
        apn=parcel.apn,
        county_fips=parcel.county_fips,
        lot_sqft=parcel.lot_sqft,
        zoning_code=parcel.zoning_code,
        zoning_allows_surface_parking=parcel.zoning_allows_surface_parking,
        is_corner_lot=parcel.is_corner_lot,
        distance_to_nearest_demand_m=parcel.distance_to_nearest_demand_m,
    )
    result = score_parcel(feature, pilot_id)
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


def _to_multi(geom: Polygon | MultiPolygon) -> MultiPolygon:
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    return geom


@celery.task(name="app.tasks.run_pipeline")
def run_pipeline(parcel_id: str) -> dict[str, Any]:
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

        feature = ParcelFeature(
            apn=parcel.apn,
            county_fips=parcel.county_fips,
            lot_sqft=parcel.lot_sqft,
            zoning_code=parcel.zoning_code,
            zoning_allows_surface_parking=parcel.zoning_allows_surface_parking,
            is_corner_lot=parcel.is_corner_lot,
            distance_to_nearest_demand_m=parcel.distance_to_nearest_demand_m,
        )
        score = score_parcel(feature, pilot_ent)
        score_strategic = score_parcel(feature, pilot_str)

        db.execute(
            delete(ParcelScore).where(
                ParcelScore.parcel_id == parcel.id,
                ParcelScore.score_profile.in_(PIPELINE_PROFILES),
            )
        )
        db.add(
            ParcelScore(
                id=uuid.uuid4(),
                parcel_id=parcel.id,
                score_profile=ENTITLEMENT,
                total_score=score.total_score,
                breakdown=score.breakdown.model_dump(),
                pilot_snapshot=score.pilot_snapshot,
            )
        )
        db.add(
            ParcelScore(
                id=uuid.uuid4(),
                parcel_id=parcel.id,
                score_profile=STRATEGIC,
                total_score=score_strategic.total_score,
                breakdown=score_strategic.breakdown.model_dump(),
                pilot_snapshot=score_strategic.pilot_snapshot,
            )
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

        db.add(
            ApprovalRequest(
                id=uuid.uuid4(),
                type="deal_memo_publish",
                status="pending",
                payload=memo_payload,
            )
        )
        db.add(
            ApprovalRequest(
                id=uuid.uuid4(),
                type="contract_send",
                status="pending",
                payload=contract_payload,
            )
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


@celery.task(name="app.tasks.enqueue_unscored_pipelines_scheduled")
def enqueue_unscored_pipelines_scheduled(limit: int = 100) -> dict[str, Any]:
    """Beat: enqueue ``run_pipeline`` for parcels missing entitlement **or** strategic scores."""
    out = enqueue_incomplete_pipeline_jobs(limit)
    if out["enqueued"]:
        logger.info(
            "enqueue_unscored_pipelines_scheduled: enqueued %s incomplete pipeline(s)",
            out["enqueued"],
        )
    return out


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
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "auto_run_pipeline": auto_run_pipeline,
            },
        )
        if auto_run_pipeline and ids:
            for pid in ids[: max(0, max_auto_pipeline)]:
                run_pipeline.delay(pid)
            if len(ids) > max_auto_pipeline:
                logger.warning(
                    "ingest_geojson_path: auto_run_pipeline capped at %s of %s parcels",
                    max_auto_pipeline,
                    len(ids),
                )
        label = Path(path).name
        ingest_detail = (
            f"File `{label}` — inserted *{inserted}*, updated *{updated}*, skipped *{skipped}*."
        )
        if auto_run_pipeline and ids:
            ingest_detail += f" Pipelines enqueued: *{min(len(ids), max_auto_pipeline)}*."
        post_agent_event_to_slack(get_settings(), agent="Ingest agent", detail=ingest_detail)
        return {
            "parcel_ids": ids,
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "pipelines_enqueued": min(len(ids), max_auto_pipeline) if auto_run_pipeline else 0,
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
            for pid in pipeline_ids[:cap]:
                run_pipeline.delay(pid)
                enq += 1
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
) -> dict[str, Any]:
    """Recompute ``distance_to_nearest_demand_m`` from pilot.yaml demand generators (centroid → POI)."""
    from geoalchemy2.shape import to_shape

    from parking_ingestion.parcel_metrics import min_distance_to_generators_m

    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    if not pilot.scoring.demand_generators:
        return {"skipped": True, "reason": "no_demand_generators_in_pilot", "updated": 0}

    lim = min(max(limit, 1), 5000)
    db = _session()
    n = 0
    try:
        stmt = select(Parcel).where(Parcel.footprint.isnot(None))
        cf = (county_fips or "").strip()
        if cf:
            stmt = stmt.where(Parcel.county_fips == cf)
        stmt = stmt.order_by(Parcel.created_at.desc()).limit(lim)
        for parcel in db.scalars(stmt):
            geom = to_shape(parcel.footprint)
            if geom.is_empty:
                continue
            c = geom.centroid
            dmin = min_distance_to_generators_m(c.y, c.x, pilot.scoring.demand_generators)
            parcel.distance_to_nearest_demand_m = dmin
            db.add(parcel)
            db.flush()
            _upsert_identification_score(db, parcel)
            n += 1
        db.commit()
        post_agent_event_to_slack(
            settings,
            agent="Beacon (demand distance refresh)",
            detail=f"Refreshed demand distance for *{n}* parcel(s)" + (f" in `{cf}`." if cf else "."),
        )
        return {"updated": n, "county_fips": cf or None, "limit": lim}
    finally:
        db.close()


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
        blocks, fallback = build_slack_digest_blocks(db, hours=4)
        posted = post_digest_to_slack(settings, blocks, fallback)
        return {"skipped": False, **posted}
    except Exception:
        logger.exception("slack_agent_digest failed")
        raise
    finally:
        db.close()
