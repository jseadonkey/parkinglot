"""Aggregate counts for CSV export / stakeholder readiness (Phase A diagnostics)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Parcel, ParcelScore
from app.scoring_profiles import IDENTIFICATION, ENTITLEMENT, STRATEGIC


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * float(part) / float(total), 2)


def export_readiness_summary(db: Session) -> dict[str, Any]:
    """Return parcel coverage stats for key CSV columns and score profiles."""
    total = int(db.scalar(select(func.count()).select_from(Parcel)) or 0)

    def count_where(condition: Any) -> int:
        return int(db.scalar(select(func.count()).select_from(Parcel).where(condition)) or 0)

    no_footprint = count_where(Parcel.footprint.is_(None))
    no_zoning = count_where(Parcel.zoning_code.is_(None))
    no_lot_sqft = count_where(Parcel.lot_sqft.is_(None))
    no_demand_m = count_where(Parcel.distance_to_nearest_demand_m.is_(None))

    miss_ident = count_where(
        ~exists(
            select(1).where(
                ParcelScore.parcel_id == Parcel.id,
                ParcelScore.score_profile == IDENTIFICATION,
            )
        )
    )
    miss_ent = count_where(
        ~exists(
            select(1).where(
                ParcelScore.parcel_id == Parcel.id,
                ParcelScore.score_profile == ENTITLEMENT,
            )
        )
    )
    miss_str = count_where(
        ~exists(
            select(1).where(
                ParcelScore.parcel_id == Parcel.id,
                ParcelScore.score_profile == STRATEGIC,
            )
        )
    )
    miss_pair = count_where(
        or_(
            ~exists(
                select(1).where(
                    ParcelScore.parcel_id == Parcel.id,
                    ParcelScore.score_profile == ENTITLEMENT,
                )
            ),
            ~exists(
                select(1).where(
                    ParcelScore.parcel_id == Parcel.id,
                    ParcelScore.score_profile == STRATEGIC,
                )
            ),
        )
    )

    return {
        "parcel_row_total": total,
        "parcels_missing_footprint": {"count": no_footprint, "pct": _pct(no_footprint, total)},
        "parcels_missing_zoning_code": {"count": no_zoning, "pct": _pct(no_zoning, total)},
        "parcels_missing_lot_sqft": {"count": no_lot_sqft, "pct": _pct(no_lot_sqft, total)},
        "parcels_missing_distance_to_nearest_demand_m": {
            "count": no_demand_m,
            "pct": _pct(no_demand_m, total),
        },
        "parcels_missing_score_identification": {"count": miss_ident, "pct": _pct(miss_ident, total)},
        "parcels_missing_score_entitlement": {"count": miss_ent, "pct": _pct(miss_ent, total)},
        "parcels_missing_score_strategic": {"count": miss_str, "pct": _pct(miss_str, total)},
        "parcels_missing_entitlement_or_strategic": {"count": miss_pair, "pct": _pct(miss_pair, total)},
        "recommended_next_steps": [
            "If entitlement or strategic gaps: POST /internal/pipeline/enqueue-incomplete?limit=500",
            "If identification gaps: re-ingest or run identification upsert (normally set on ingest).",
            "If demand distance gaps: POST /internal/metrics/refresh-demand-distances?limit=2000",
            "If zoning gaps: spatial join → GeoJSON overlay → POST /internal/ingest/merge-geojson-attributes",
        ],
    }
