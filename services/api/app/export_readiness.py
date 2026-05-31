"""Aggregate counts for CSV export / stakeholder readiness (Phase A–C diagnostics)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Parcel, ParcelScore
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * float(part) / float(total), 2)


def export_readiness_summary(db: Session, *, in_scope_only: bool = True) -> dict[str, Any]:
    """Return parcel coverage stats for scores, CSV columns, and owner outreach brief."""
    scope = Parcel.pilot_in_scope.is_(True) if in_scope_only else True
    total = int(db.scalar(select(func.count()).select_from(Parcel).where(scope)) or 0)

    def count_where(condition: Any) -> int:
        return int(db.scalar(select(func.count()).select_from(Parcel).where(scope, condition)) or 0)

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

    miss_brief = count_where(Parcel.owner_outreach_brief.is_(None))

    recommended_next_steps: list[str] = [
        "If entitlement or strategic gaps: POST /internal/pipeline/enqueue-incomplete?limit=500",
        "If identification gaps: POST /internal/metrics/refresh-identification-scores?limit=2000 (or re-ingest).",
        "If demand distance gaps: POST /internal/metrics/refresh-demand-distances?limit=2000",
        "If zoning gaps: spatial join → GeoJSON overlay → "
        "POST /internal/ingest/merge-geojson-attributes (or scripts/execute-phase-b.sh).",
    ]
    if miss_brief > 0:
        recommended_next_steps.append(
            "If owner outreach brief gaps: POST /internal/pipeline/enqueue-incomplete, "
            "per-parcel POST /parcels/{id}/outreach/recompute, or scripts/execute-phase-c.sh (smoke) "
            "— see docs/OPERATIONS.md (owner outreach)."
        )

    return {
        "parcel_row_total": total,
        "pilot_scope": "in_scope_only" if in_scope_only else "all_rows",
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
        "parcels_missing_owner_outreach_brief": {"count": miss_brief, "pct": _pct(miss_brief, total)},
        "recommended_next_steps": recommended_next_steps,
    }
