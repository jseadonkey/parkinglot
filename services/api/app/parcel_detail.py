"""Aggregate parcel detail for operator console (scores, owners, memos, approvals)."""

from __future__ import annotations

import uuid
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import ApprovalRequest, ContractDraft, DealMemo, OwnerCandidateRow, Parcel, ParcelScore, WorkflowRun
from app.owner_record_view import build_owner_record_view
from app.pipeline_gates import parcel_qualifies_for_human_gate
from app.scoring_profiles import ALL_PROFILES
from parking_core.pilot import load_pilot_config

_ASSESSOR_KEYS: tuple[tuple[str, str], ...] = (
    ("OWNER_NAME", "Owner (assessor roll)"),
    ("SITUS_ADDRESS", "Situs address"),
    ("SITUS_CITY_NM", "Situs city"),
    ("SITUS_ZIP_NR", "Situs ZIP"),
    ("SUB_ADDRESS", "Sub / unit address"),
    ("LANDUSE_CD", "Land use code (DOR)"),
    ("VALUE_LAND", "Assessed land value"),
    ("VALUE_BLDG", "Assessed building value"),
    ("DATA_LINK", "County assessor link"),
    ("PARCEL_ID_NR", "County parcel ID"),
    ("ZONING_JURISDICTION", "Zoning jurisdiction"),
)


def _king_county_erealproperty_url(apn: str) -> str | None:
    if not apn or "-" not in apn:
        return None
    pin = apn.split("-")[-1].strip()
    if not pin:
        return None
    return f"https://blue.kingcounty.com/Assessor/eRealProperty/Detail.aspx?ParcelNbr={pin}"


def _clean_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _owner_record(
    raw: dict[str, Any] | None,
    *,
    apn: str,
    county_fips: str,
) -> dict[str, Any]:
    """Taxpayer row from ``raw_properties.owner_record`` (King County assessor enrichment)."""
    block = raw.get("owner_record") if isinstance(raw, dict) else None
    if not isinstance(block, dict):
        block = {}

    def pick(*keys: str) -> str | None:
        for k in keys:
            v = _clean_str(block.get(k))
            if v:
                return v
        return None

    land = block.get("appraised_land")
    impr = block.get("appraised_improvements")
    url = _clean_str(block.get("erealproperty_url"))
    if not url and county_fips == "53033":
        url = _king_county_erealproperty_url(apn)

    return {
        "taxpayer_name": pick("taxpayer_name"),
        "taxpayer_attn": pick("taxpayer_attn"),
        "mailing_address": pick("mailing_address"),
        "appraised_land": float(land) if land is not None else None,
        "appraised_improvements": float(impr) if impr is not None else None,
        "property_type": pick("property_type"),
        "erealproperty_url": url,
        "data_source": pick("data_source"),
        "enriched_at": pick("enriched_at"),
    }


def _assessor_summary(raw: dict[str, Any] | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for key, label in _ASSESSOR_KEYS:
        val = raw.get(key)
        if val is None or val == "":
            continue
        out[label] = str(val)
    return out


def _centroid_lat_lon(parcel: Parcel) -> tuple[float | None, float | None]:
    if parcel.footprint is None:
        return None, None
    try:
        c = to_shape(parcel.footprint).centroid
        return float(c.y), float(c.x)
    except Exception:
        return None, None


def build_parcel_detail(db: Session, parcel_id: uuid.UUID) -> dict[str, Any] | None:
    parcel = db.get(Parcel, parcel_id)
    if parcel is None:
        return None

    settings = get_settings()
    pilot_ent = load_pilot_config(settings.pilot_config_path)
    pilot_str = load_pilot_config(settings.pilot_strategic_config_path)
    floor_e = float(pilot_ent.scoring.qualified_min_score)
    floor_s = float(pilot_str.scoring.qualified_min_score)

    scores: list[ParcelScore] = []
    ent_score: float | None = None
    str_score: float | None = None
    for profile in ALL_PROFILES:
        row = db.scalars(
            select(ParcelScore)
            .where(ParcelScore.parcel_id == parcel_id)
            .where(ParcelScore.score_profile == profile)
            .order_by(desc(ParcelScore.created_at))
            .limit(1)
        ).first()
        if row is not None:
            scores.append(row)
            if profile == "entitlement":
                ent_score = float(row.total_score)
            elif profile == "strategic":
                str_score = float(row.total_score)

    dual_qualified = False
    if ent_score is not None and str_score is not None:
        dual_qualified = parcel_qualifies_for_human_gate(
            ent_score,
            str_score,
            min_entitlement=floor_e,
            min_strategic=floor_s,
        )

    owners = list(
        db.scalars(
            select(OwnerCandidateRow)
            .where(OwnerCandidateRow.parcel_id == parcel_id)
            .order_by(desc(OwnerCandidateRow.confidence), OwnerCandidateRow.display_name)
        ).all()
    )
    memos = list(
        db.scalars(
            select(DealMemo).where(DealMemo.parcel_id == parcel_id).order_by(desc(DealMemo.created_at))
        ).all()
    )
    contracts = list(
        db.scalars(
            select(ContractDraft)
            .where(ContractDraft.parcel_id == parcel_id)
            .order_by(desc(ContractDraft.created_at))
        ).all()
    )
    runs = list(
        db.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.parcel_id == parcel_id)
            .order_by(desc(WorkflowRun.created_at))
            .limit(50)
        ).all()
    )

    pid_str = str(parcel_id)
    pid_expr = ApprovalRequest.payload["parcel_id"].as_string()
    approvals = list(
        db.scalars(
            select(ApprovalRequest)
            .where(pid_expr == pid_str)
            .order_by(desc(ApprovalRequest.created_at))
            .limit(50)
        ).all()
    )

    lat, lon = _centroid_lat_lon(parcel)
    raw = parcel.raw_properties if isinstance(parcel.raw_properties, dict) else None

    return {
        "id": parcel.id,
        "apn": parcel.apn,
        "county_fips": parcel.county_fips,
        "lot_sqft": parcel.lot_sqft,
        "zoning_code": parcel.zoning_code,
        "zoning_allows_surface_parking": parcel.zoning_allows_surface_parking,
        "is_corner_lot": parcel.is_corner_lot,
        "distance_to_nearest_demand_m": parcel.distance_to_nearest_demand_m,
        "distance_to_nearest_comp_parking_m": parcel.distance_to_nearest_comp_parking_m,
        "nearest_parking_comp": parcel.nearest_parking_comp,
        "pilot_in_scope": parcel.pilot_in_scope,
        "has_footprint": parcel.footprint is not None,
        "centroid_lat": lat,
        "centroid_lon": lon,
        "owner_outreach_brief": parcel.owner_outreach_brief,
        "raw_properties": raw,
        "assessor_summary": _assessor_summary(raw),
        "owner_record": build_owner_record_view(parcel, owners),
        "created_at": parcel.created_at,
        "scores": scores,
        "owners": owners,
        "memos": memos,
        "contract_drafts": contracts,
        "approvals": approvals,
        "workflow_runs": runs,
        "qualification": {
            "meets_entitlement_floor": ent_score is not None and ent_score >= floor_e,
            "meets_strategic_floor": str_score is not None and str_score >= floor_s,
            "dual_qualified": dual_qualified,
            "qualified_min_entitlement": floor_e,
            "qualified_min_strategic": floor_s,
            "latest_entitlement_score": ent_score,
            "latest_strategic_score": str_score,
        },
        "pilot_region": pilot_ent.region.name,
    }
