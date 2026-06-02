"""Aggregate counts for CSV export / stakeholder readiness (Phase A–C diagnostics)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Parcel, ParcelScore
from app.pipeline_funnel import (
    count_where,
    identification_prescreen_floor,
    identification_prescreen_qualified,
    missing_pipeline_pair,
    pipeline_funnel_backlog,
    ruled_out_by_prescreen,
)
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * float(part) / float(total), 2)


def export_readiness_summary(db: Session) -> dict[str, Any]:
    """Return parcel coverage stats for scores, CSV columns, and owner outreach brief."""
    total = int(db.scalar(select(func.count()).select_from(Parcel)) or 0)
    floor_i = identification_prescreen_floor()

    no_footprint = count_where(db, Parcel.footprint.is_(None))
    no_zoning = count_where(db, Parcel.zoning_code.is_(None))
    no_lot_sqft = count_where(db, Parcel.lot_sqft.is_(None))
    no_demand_m = count_where(db, Parcel.distance_to_nearest_demand_m.is_(None))

    miss_ident = count_where(
        db,
        ~exists(
            select(1).where(
                ParcelScore.parcel_id == Parcel.id,
                ParcelScore.score_profile == IDENTIFICATION,
            )
        ),
    )
    miss_ent = count_where(
        db,
        ~exists(
            select(1).where(
                ParcelScore.parcel_id == Parcel.id,
                ParcelScore.score_profile == ENTITLEMENT,
            )
        ),
    )
    miss_str = count_where(
        db,
        ~exists(
            select(1).where(
                ParcelScore.parcel_id == Parcel.id,
                ParcelScore.score_profile == STRATEGIC,
            )
        ),
    )
    miss_pair = count_where(db, missing_pipeline_pair())
    prescreen_qualified = count_where(db, identification_prescreen_qualified(floor_i))
    funnel_backlog = count_where(db, pipeline_funnel_backlog(floor_i))
    prescreen_ruled_out = count_where(db, ruled_out_by_prescreen(floor_i))

    miss_brief = count_where(db, Parcel.owner_outreach_brief.is_(None))

    recommended_next_steps: list[str] = [
        f"Funnel backlog (prescreen ≥ {floor_i:.0f}, missing Atlas/Beacon): "
        "POST /internal/pipeline/enqueue-incomplete?limit=500 — scheduled Beat uses the same gate.",
        "Gross count `parcels_missing_entitlement_or_strategic` includes prescreen ruled-out lots; "
        "use `parcels_pipeline_funnel_backlog` for work that should run `run_pipeline`.",
        "If identification gaps: POST /internal/metrics/refresh-identification-scores?limit=2000 (or re-ingest).",
        "If demand distance gaps: POST /internal/metrics/refresh-demand-distances?limit=2000",
        "If zoning gaps: spatial join → GeoJSON overlay → "
        "POST /internal/ingest/merge-geojson-attributes (or scripts/execute-phase-b.sh).",
    ]
    if miss_brief > 0:
        recommended_next_steps.append(
            "If owner outreach brief gaps: enqueue prescreen-qualified parcels only, "
            "per-parcel POST /parcels/{id}/outreach/recompute, or scripts/execute-phase-c.sh (smoke) "
            "— see docs/OPERATIONS.md (owner outreach)."
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
        "parcels_prescreen_qualified": {
            "count": prescreen_qualified,
            "pct": _pct(prescreen_qualified, total),
            "floor": floor_i,
        },
        "parcels_pipeline_funnel_backlog": {
            "count": funnel_backlog,
            "pct": _pct(funnel_backlog, total),
            "floor": floor_i,
        },
        "parcels_ruled_out_by_prescreen": {
            "count": prescreen_ruled_out,
            "pct": _pct(prescreen_ruled_out, total),
            "floor": floor_i,
        },
        "parcels_missing_owner_outreach_brief": {"count": miss_brief, "pct": _pct(miss_brief, total)},
        "recommended_next_steps": recommended_next_steps,
    }
