from __future__ import annotations

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.db.models import ParkingRateComp
from parking_core.pilot import ParkingRateCompObservation


def fetch_parking_rate_comps_near(
    db: Session,
    *,
    lat: float,
    lon: float,
    radius_m: float,
) -> list[ParkingRateCompObservation]:
    """Active comps whose point is within ``radius_m`` (meters) of ``(lat, lon)`` using geography."""
    pt = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
    stmt = (
        select(
            ParkingRateComp.name,
            ParkingRateComp.hourly_mid_usd,
            ParkingRateComp.source_note,
            func.ST_Y(ParkingRateComp.location).label("lat"),
            func.ST_X(ParkingRateComp.location).label("lon"),
        )
        .where(ParkingRateComp.active.is_(True))
        .where(
            func.ST_DWithin(
                cast(ParkingRateComp.location, Geography),
                cast(pt, Geography),
                radius_m,
            ),
        )
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
            ),
        )
    return out
