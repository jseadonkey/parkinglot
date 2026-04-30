from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from geoalchemy2.elements import WKTElement
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.celery_app import celery
from app.config import get_settings
from app.contract_render import render_ground_lease_draft
from app.db.models import ApprovalRequest, ContractDraft, DealMemo, OwnerCandidateRow, Parcel, ParcelScore, WorkflowRun
from app.db.session import SessionLocal
from app.memo_render import build_deal_memo_markdown
from app.slack_digest import build_slack_digest_blocks, post_digest_to_slack
from app.storage import put_text_object
from parking_core.models import ParcelFeature
from parking_core.pilot import load_pilot_config
from parking_enrichment.pipeline import enrich_from_parcel_row
from parking_scoring.engine import score_parcel
from parking_workflows.state import WorkflowStatus, WorkflowStep

logger = logging.getLogger(__name__)


def _session() -> Session:
    return SessionLocal()


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
        pilot = load_pilot_config(get_settings().pilot_config_path)

        feature = ParcelFeature(
            apn=parcel.apn,
            county_fips=parcel.county_fips,
            lot_sqft=parcel.lot_sqft,
            zoning_code=parcel.zoning_code,
            zoning_allows_surface_parking=parcel.zoning_allows_surface_parking,
            is_corner_lot=parcel.is_corner_lot,
            distance_to_nearest_demand_m=parcel.distance_to_nearest_demand_m,
        )
        score = score_parcel(feature, pilot)

        db.execute(delete(ParcelScore).where(ParcelScore.parcel_id == parcel.id))
        ps = ParcelScore(
            id=uuid.uuid4(),
            parcel_id=parcel.id,
            total_score=score.total_score,
            breakdown=score.breakdown.model_dump(),
            pilot_snapshot=score.pilot_snapshot,
        )
        db.add(ps)

        run.current_step = WorkflowStep.enrich.value
        db.add(run)
        db.commit()

        db.execute(delete(OwnerCandidateRow).where(OwnerCandidateRow.parcel_id == parcel.id))
        for cand in enrich_from_parcel_row(parcel.raw_properties or {}):
            db.add(
                OwnerCandidateRow(
                    id=uuid.uuid4(),
                    parcel_id=parcel.id,
                    display_name=cand.display_name,
                    kind=cand.kind.value,
                    confidence=cand.confidence,
                    source=cand.source,
                    raw=cand.raw,
                )
            )
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
        return {"workflow_run_id": str(run.id), "status": run.status}
    except Exception as exc:  # noqa: BLE001
        run.status = WorkflowStatus.failed.value
        run.error = str(exc)
        db.add(run)
        db.commit()
        raise
    finally:
        db.close()


@celery.task(name="app.tasks.ingest_geojson_path")
def ingest_geojson_path(path: str) -> list[str]:
    from parking_ingestion.geojson_loader import iter_parcels_from_geojson_dict, load_geojson_path

    data = load_geojson_path(Path(path))
    db = _session()
    ids: list[str] = []
    try:
        pilot = load_pilot_config(get_settings().pilot_config_path)
        for attrs, geom in iter_parcels_from_geojson_dict(data):
            county = str(attrs["county_fips"])
            if pilot.region.county_fips and county not in pilot.region.county_fips:
                continue
            multi = _to_multi(geom)  # type: ignore[arg-type]
            footprint = WKTElement(multi.wkt, srid=4326)
            p = Parcel(
                id=uuid.uuid4(),
                apn=str(attrs["apn"]),
                county_fips=county,
                lot_sqft=float(attrs["lot_sqft"]) if attrs.get("lot_sqft") is not None else None,
                zoning_code=str(attrs["zoning_code"]) if attrs.get("zoning_code") else None,
                zoning_allows_surface_parking=bool(attrs.get("zoning_allows_surface_parking")),
                is_corner_lot=bool(attrs.get("is_corner_lot")),
                distance_to_nearest_demand_m=float(attrs["distance_to_nearest_demand_m"])
                if attrs.get("distance_to_nearest_demand_m") is not None
                else None,
                raw_properties=attrs.get("raw_properties") or {},
                footprint=footprint,
            )
            db.add(p)
            db.flush()
            ids.append(str(p.id))
        db.commit()
        write_audit(
            db,
            actor="system",
            action="parcels_ingested",
            entity_type="parcel",
            entity_id=None,
            meta={"parcel_ids": ids, "source_path": path},
        )
        return ids
    finally:
        db.close()


@celery.task(name="app.tasks.slack_agent_digest")
def slack_agent_digest() -> dict[str, Any]:
    """Scheduled standup: post a Block Kit digest to Slack (worker executes; Beat only schedules)."""
    settings = get_settings()
    if not (settings.slack_bot_token or "").strip() or not (settings.slack_digest_channel_id or "").strip():
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
