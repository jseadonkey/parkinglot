"""Nearby qualified parcels and parking revenue context for operator deal review."""

from __future__ import annotations

import uuid
from typing import Any

from geoalchemy2 import Geography
from geoalchemy2.shape import to_shape
from sqlalchemy import and_, cast, desc, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Parcel, ParcelScore
from app.rate_comps import merged_rate_comps_near
from app.scoring_profiles import ENTITLEMENT
from parking_core.pilot import ParkingRateCompObservation, PilotConfig, load_pilot_config
from parking_core.revenue_estimate import estimate_parking_revenue

__all__ = [
    "attach_revenue_summaries",
    "build_parcel_deal_context",
    "estimate_parking_revenue",
    "parcel_centroid_lat_lon",
    "qualified_min_entitlement_score",
    "rate_comps_for_parcel",
    "revenue_hint_for_parcel",
    "revenue_summary_for_parcel",
]


def qualified_min_entitlement_score(pilot: PilotConfig) -> float:
    return float(pilot.scoring.qualified_min_score)


def parcel_centroid_lat_lon(parcel: Parcel) -> tuple[float, float] | None:
    if parcel.footprint is None:
        return None
    try:
        geom = to_shape(parcel.footprint)
        c = geom.centroid
        return float(c.y), float(c.x)
    except Exception:
        return None


def rate_comps_for_parcel(
    db: Session,
    *,
    lat: float,
    lon: float,
    pilot: PilotConfig,
) -> list[ParkingRateCompObservation]:
    return merged_rate_comps_near(db, lat=lat, lon=lon, pilot=pilot)


def _latest_entitlement_subq():
    agg = (
        select(
            ParcelScore.parcel_id.label("pid"),
            func.max(ParcelScore.created_at).label("mx"),
        )
        .where(ParcelScore.score_profile == ENTITLEMENT)
        .group_by(ParcelScore.parcel_id)
        .subquery()
    )
    return (
        select(
            ParcelScore.parcel_id.label("parcel_id"),
            ParcelScore.total_score.label("ent_score"),
        )
        .join(
            agg,
            and_(
                ParcelScore.parcel_id == agg.c.pid,
                ParcelScore.created_at == agg.c.mx,
            ),
        )
        .where(ParcelScore.score_profile == ENTITLEMENT)
        .subquery()
    )


def nearby_qualified_parcels(
    db: Session,
    *,
    parcel_id: uuid.UUID,
    lat: float,
    lon: float,
    radius_m: float,
    min_entitlement_score: float,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Other entitlement-qualified parcels within ``radius_m`` of ``(lat, lon)``."""
    cap = min(max(limit, 1), 50)
    pt = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
    ent = _latest_entitlement_subq()
    dist_m = func.ST_Distance(
        cast(Parcel.footprint, Geography),
        cast(pt, Geography),
    ).label("distance_m")
    stmt = (
        select(
            Parcel.id,
            Parcel.apn,
            Parcel.county_fips,
            Parcel.lot_sqft,
            Parcel.zoning_code,
            ent.c.ent_score,
            dist_m,
        )
        .join(ent, Parcel.id == ent.c.parcel_id)
        .where(Parcel.id != parcel_id)
        .where(Parcel.footprint.isnot(None))
        .where(ent.c.ent_score >= min_entitlement_score)
        .where(
            func.ST_DWithin(
                cast(Parcel.footprint, Geography),
                cast(pt, Geography),
                radius_m,
            ),
        )
        .order_by(desc(ent.c.ent_score), dist_m)
        .limit(cap)
    )
    rows: list[dict[str, Any]] = []
    for row in db.execute(stmt):
        rows.append(
            {
                "parcel_id": str(row.id),
                "apn": row.apn,
                "county_fips": row.county_fips,
                "lot_sqft": row.lot_sqft,
                "zoning_code": row.zoning_code,
                "entitlement_score": float(row.ent_score),
                "distance_m": round(float(row.distance_m), 1) if row.distance_m is not None else None,
            },
        )
    return rows


def revenue_summary_for_parcel(
    db: Session,
    parcel: Parcel,
    *,
    pilot: PilotConfig | None = None,
) -> dict[str, float | bool | int | str | None]:
    """Compact revenue + stall + comp summary for list/board views (any pilot region)."""
    settings = get_settings()
    cfg = pilot or load_pilot_config(settings.pilot_config_path)
    empty: dict[str, float | bool | int | str | None] = {
        "revenue_available": False,
        "monthly_gross_usd": None,
        "monthly_gross_low_usd": None,
        "monthly_gross_high_usd": None,
        "stalls_estimated": None,
        "stalls_low": None,
        "stalls_high": None,
        "hourly_rate_weighted_usd": None,
        "hourly_rate_median_usd": None,
        "comp_count": None,
        "nearest_comp_name": None,
        "nearest_comp_distance_m": None,
        "market_confidence": None,
        "market_confidence_tier": None,
        "strong_comp_count": None,
        "monthly_gross_raw_usd": None,
        "market_evidence_notes": None,
    }
    centroid = parcel_centroid_lat_lon(parcel)
    if centroid is None:
        return empty
    lat, lon = centroid
    comps = rate_comps_for_parcel(db, lat=lat, lon=lon, pilot=cfg)
    est = estimate_parking_revenue(
        lot_sqft=parcel.lot_sqft,
        comps=comps,
        lat=lat,
        lon=lon,
        is_corner_lot=bool(parcel.is_corner_lot),
    )
    if not est.get("available"):
        return empty
    primary = est.get("primary_comps") or []
    top = primary[0] if primary else None
    return {
        "revenue_available": True,
        "monthly_gross_usd": float(est["monthly_gross_usd"]) if est.get("monthly_gross_usd") is not None else None,
        "monthly_gross_low_usd": (
            float(est["monthly_gross_low_usd"]) if est.get("monthly_gross_low_usd") is not None else None
        ),
        "monthly_gross_high_usd": (
            float(est["monthly_gross_high_usd"]) if est.get("monthly_gross_high_usd") is not None else None
        ),
        "stalls_estimated": int(est["stalls_estimated"]) if est.get("stalls_estimated") is not None else None,
        "stalls_low": int(est["stalls_low"]) if est.get("stalls_low") is not None else None,
        "stalls_high": int(est["stalls_high"]) if est.get("stalls_high") is not None else None,
        "hourly_rate_weighted_usd": (
            float(est["hourly_rate_weighted_usd"]) if est.get("hourly_rate_weighted_usd") is not None else None
        ),
        "hourly_rate_median_usd": (
            float(est["hourly_rate_median_usd"]) if est.get("hourly_rate_median_usd") is not None else None
        ),
        "comp_count": int(est["comp_count"]) if est.get("comp_count") is not None else None,
        "nearest_comp_name": str(top["name"]) if top else None,
        "nearest_comp_distance_m": (
            float(top["distance_m"])
            if top and top.get("distance_m") is not None
            else est.get("nearest_comp_distance_m")
        ),
        "market_confidence": float(est["market_confidence"]) if est.get("market_confidence") is not None else None,
        "market_confidence_tier": str(est.get("market_confidence_tier") or ""),
        "strong_comp_count": int(est["strong_comp_count"]) if est.get("strong_comp_count") is not None else None,
        "monthly_gross_raw_usd": (
            float(est["monthly_gross_raw_usd"]) if est.get("monthly_gross_raw_usd") is not None else None
        ),
        "market_evidence_notes": list(est.get("market_evidence_notes") or []),
    }


def revenue_hint_for_parcel(
    db: Session,
    parcel: Parcel,
    *,
    pilot: PilotConfig | None = None,
) -> dict[str, float | bool | None]:
    """Lightweight gross-revenue hint for list views (top parcels only)."""
    summary = revenue_summary_for_parcel(db, parcel, pilot=pilot)
    return {
        "revenue_available": bool(summary.get("revenue_available")),
        "monthly_gross_usd": summary.get("monthly_gross_usd"),
    }


def attach_revenue_summaries(
    db: Session,
    *,
    parcel_ids: list[uuid.UUID],
    pilot: PilotConfig,
) -> dict[str, dict[str, float | bool | int | str | None]]:
    """Batch revenue summaries keyed by parcel id string."""
    if not parcel_ids:
        return {}
    rows = db.scalars(select(Parcel).where(Parcel.id.in_(parcel_ids))).all()
    out: dict[str, dict[str, float | bool | int | str | None]] = {}
    for parcel in rows:
        out[str(parcel.id)] = revenue_summary_for_parcel(db, parcel, pilot=pilot)
    return out


def build_parcel_deal_context(db: Session, parcel_id: uuid.UUID) -> dict[str, Any]:
    parcel = db.get(Parcel, parcel_id)
    if parcel is None:
        return {"found": False}

    settings = get_settings()
    pilot = load_pilot_config(settings.pilot_config_path)
    floor_ent = float(pilot.scoring.qualified_min_score)
    centroid = parcel_centroid_lat_lon(parcel)
    radius_m = float(pilot.scoring.parking_rate_comp_radius_m or 2500.0)

    comps: list[ParkingRateCompObservation] = []
    nearby: list[dict[str, Any]] = []
    revenue: dict[str, Any] = {"available": False, "reason": "missing footprint"}
    if centroid is not None:
        lat, lon = centroid
        comps = rate_comps_for_parcel(db, lat=lat, lon=lon, pilot=pilot)
        nearby = nearby_qualified_parcels(
            db,
            parcel_id=parcel_id,
            lat=lat,
            lon=lon,
            radius_m=radius_m,
            min_entitlement_score=floor_ent,
        )
        revenue = estimate_parking_revenue(
            lot_sqft=parcel.lot_sqft,
            comps=comps,
            lat=lat,
            lon=lon,
            is_corner_lot=bool(parcel.is_corner_lot),
        )

    ent_row = db.scalars(
        select(ParcelScore)
        .where(ParcelScore.parcel_id == parcel_id)
        .where(ParcelScore.score_profile == ENTITLEMENT)
        .order_by(ParcelScore.created_at.desc())
        .limit(1),
    ).first()

    rate_comps_out = revenue.get("primary_comps") or []
    if not rate_comps_out and revenue.get("comps_weighted"):
        rate_comps_out = revenue["comps_weighted"][:8]
    elif not rate_comps_out:
        rate_comps_out = [
            {
                "name": c.name,
                "lat": c.lat,
                "lon": c.lon,
                "hourly_mid_usd": c.hourly_mid_usd,
                "source_note": c.source_note,
                "origin": c.origin,
                "distance_m": c.distance_m,
            }
            for c in comps
        ]

    revenue_out = {k: v for k, v in revenue.items() if k not in ("comps_weighted", "primary_comps")}

    return {
        "found": True,
        "parcel_id": str(parcel_id),
        "apn": parcel.apn,
        "county_fips": parcel.county_fips,
        "lot_sqft": parcel.lot_sqft,
        "centroid": {"lat": centroid[0], "lon": centroid[1]} if centroid else None,
        "entitlement_score": float(ent_row.total_score) if ent_row else None,
        "qualified_floor": floor_ent,
        "rate_comp_radius_m": radius_m,
        "rate_comps": rate_comps_out,
        "revenue_estimate": revenue_out,
        "nearby_qualified_parcels": nearby,
    }
