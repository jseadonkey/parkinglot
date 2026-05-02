"""Shared SQL helpers for parcel CSV exports (latest scores per profile).

Uses the same profile strings as ``app.scoring_profiles`` (identification, entitlement, strategic).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def ensure_api_path() -> None:
    api_root = repo_root() / "services" / "api"
    root = str(api_root)
    if root not in sys.path:
        sys.path.insert(0, root)


def normalize_database_url(raw: str) -> str:
    """Ensure SQLAlchemy uses the psycopg (v3) driver, matching the API stack."""
    s = raw.strip()
    if s.startswith("postgresql+psycopg://"):
        return s
    if s.startswith("postgresql+psycopg2://"):
        return s.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    if s.startswith("postgresql://"):
        return "postgresql+psycopg://" + s.removeprefix("postgresql://")
    if s.startswith("postgres://"):
        return "postgresql+psycopg://" + s.removeprefix("postgres://")
    return s


def latest_profile_subquery(profile: str, score_label: str):
    from sqlalchemy import and_, func, select

    from app.db.models import ParcelScore

    agg = (
        select(
            ParcelScore.parcel_id.label("parcel_id"),
            func.max(ParcelScore.created_at).label("mx"),
        )
        .where(ParcelScore.score_profile == profile)
        .group_by(ParcelScore.parcel_id)
        .subquery()
    )
    return (
        select(
            ParcelScore.parcel_id,
            ParcelScore.total_score.label(score_label),
        )
        .join(
            agg,
            and_(
                ParcelScore.parcel_id == agg.c.parcel_id,
                ParcelScore.created_at == agg.c.mx,
                ParcelScore.score_profile == profile,
            ),
        )
        .subquery()
    )


def build_scored_parcels_statement(
    *,
    variant: Literal["full_csv", "visual_review"],
    limit: int | None = None,
    min_score_identification: float | None = None,
    min_score_entitlement: float | None = None,
):
    """Build SELECT for parcels with latest scores per profile.

    * **full_csv** — includes extra parcel columns; ordered by APN / county (stable dump).
    * **visual_review** — core columns + centroids; ordered by identification then entitlement
      (desc, nulls last) for shortlists.
    """
    from sqlalchemy import and_, literal_column, select

    from app.db.models import Parcel

    # Literal profile strings (ParcelScore.score_profile). Avoid importing app.scoring_profiles so
    # CSV exports work when /app/services/api in the container image lags the repo scripts checkout.
    IDENTIFICATION = "identification"
    ENTITLEMENT = "entitlement"
    STRATEGIC = "strategic"

    sq_ident = latest_profile_subquery(IDENTIFICATION, "score_identification")
    sq_ent = latest_profile_subquery(ENTITLEMENT, "score_entitlement")
    sq_str = latest_profile_subquery(STRATEGIC, "score_strategic")

    centroid_lon = literal_column("ST_X(ST_Centroid(parcels.footprint))").label("centroid_lon")
    centroid_lat = literal_column("ST_Y(ST_Centroid(parcels.footprint))").label("centroid_lat")

    if variant == "full_csv":
        cols = (
            Parcel.id.label("parcel_id"),
            Parcel.apn,
            Parcel.county_fips,
            Parcel.lot_sqft,
            Parcel.zoning_code,
            Parcel.zoning_allows_surface_parking,
            Parcel.is_corner_lot,
            Parcel.distance_to_nearest_demand_m,
            sq_ident.c.score_identification,
            sq_ent.c.score_entitlement,
            sq_str.c.score_strategic,
            centroid_lon,
            centroid_lat,
        )
        order_by = (Parcel.apn, Parcel.county_fips)
    else:
        cols = (
            Parcel.id.label("parcel_id"),
            Parcel.apn,
            Parcel.county_fips,
            Parcel.lot_sqft,
            Parcel.zoning_code,
            Parcel.zoning_allows_surface_parking,
            sq_ident.c.score_identification,
            sq_ent.c.score_entitlement,
            sq_str.c.score_strategic,
            centroid_lat,
            centroid_lon,
        )
        order_by = (
            sq_ident.c.score_identification.desc().nulls_last(),
            sq_ent.c.score_entitlement.desc().nulls_last(),
            Parcel.apn,
            Parcel.county_fips,
        )

    stmt = (
        select(*cols)
        .select_from(Parcel)
        .outerjoin(sq_ident, Parcel.id == sq_ident.c.parcel_id)
        .outerjoin(sq_ent, Parcel.id == sq_ent.c.parcel_id)
        .outerjoin(sq_str, Parcel.id == sq_str.c.parcel_id)
        .order_by(*order_by)
    )

    conds = []
    if min_score_identification is not None:
        conds.append(sq_ident.c.score_identification >= min_score_identification)
    if min_score_entitlement is not None:
        conds.append(sq_ent.c.score_entitlement >= min_score_entitlement)
    if conds:
        stmt = stmt.where(and_(*conds))

    if limit is not None:
        stmt = stmt.limit(limit)
    return stmt
