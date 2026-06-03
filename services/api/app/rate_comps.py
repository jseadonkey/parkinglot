from __future__ import annotations

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.db.models import ParkingRateComp
from parking_core.pilot import ParkingRateCompObservation, PilotConfig
from parking_core.rate_comps import filter_comps_within_radius, merge_rate_comp_sequences


def fetch_parking_rate_comps_near(
    db: Session,
    *,
    lat: float,
    lon: float,
    radius_m: float,
    limit: int = 8,
) -> list[ParkingRateCompObservation]:
    """Active comps within ``radius_m``, nearest first (up to ``limit``)."""
    pt = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
    dist_m = func.ST_Distance(
        cast(ParkingRateComp.location, Geography),
        cast(pt, Geography),
    ).label("distance_m")
    stmt = (
        select(
            ParkingRateComp.name,
            ParkingRateComp.hourly_mid_usd,
            ParkingRateComp.source_note,
            func.ST_Y(ParkingRateComp.location).label("lat"),
            func.ST_X(ParkingRateComp.location).label("lon"),
            dist_m,
        )
        .where(ParkingRateComp.active.is_(True))
        .where(
            func.ST_DWithin(
                cast(ParkingRateComp.location, Geography),
                cast(pt, Geography),
                radius_m,
            ),
        )
        .order_by(dist_m)
        .limit(max(1, limit))
    )
    out: list[ParkingRateCompObservation] = []
    for row in db.execute(stmt):
        out.append(
            ParkingRateCompObservation(
                name=row.name,
                lat=float(row.lat),
                lon=float(row.lon),
                hourly_mid_usd=float(row.hourly_mid_usd),
                source_note=row.source_note,
                origin="database",
                distance_m=round(float(row.distance_m), 1) if row.distance_m is not None else None,
            ),
        )
    return out


def merged_rate_comps_near(
    db: Session,
    *,
    lat: float,
    lon: float,
    pilot: PilotConfig,
) -> list[ParkingRateCompObservation]:
    """Postgres comps (nearest first) merged with YAML comps within radius.

    If the primary radius returns fewer comps than ``parking_rate_comp_min_for_full_credit``,
    repeats the search out to ``parking_rate_comp_expanded_radius_m``.
    """
    radius = float(pilot.scoring.parking_rate_comp_radius_m or 2500.0)
    expanded = float(getattr(pilot.scoring, "parking_rate_comp_expanded_radius_m", 7500.0) or 7500.0)
    max_used = int(getattr(pilot.scoring, "parking_rate_comp_max_used", 8) or 8)
    min_full = int(getattr(pilot.scoring, "parking_rate_comp_min_for_full_credit", 2) or 2)

    def _merge_for_radius(search_radius: float) -> list[ParkingRateCompObservation]:
        db_comps = fetch_parking_rate_comps_near(
            db, lat=lat, lon=lon, radius_m=search_radius, limit=max_used,
        )
        yaml_near = filter_comps_within_radius(
            list(pilot.scoring.parking_rate_comps or []),
            lat=lat,
            lon=lon,
            radius_m=search_radius,
        )
        return merge_rate_comp_sequences(db_comps, yaml_near)[:max_used]

    merged = _merge_for_radius(radius)
    if len(merged) < min_full and expanded > radius:
        merged = _merge_for_radius(expanded)
    return merged[:max_used]
