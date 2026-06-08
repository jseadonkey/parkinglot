"""Aggregated live stats for partner / platform showcase UI."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Parcel
from app.db.schema_compat import column_exists
from app.deal_progress import query_deal_progress_board
from app.export_readiness import export_readiness_summary
from app.parcel_scored_list import ENTITLEMENT, query_parcels_scored_list
from app.pilot_scope import pilot_scope_summary
from app.platform_samples import build_platform_sample_deliverables
from app.scoring_summary import scoring_summary_stats


def build_platform_showcase(db: Session) -> dict[str, Any]:
    scoring = scoring_summary_stats(db)
    scope = pilot_scope_summary(db)
    export = export_readiness_summary(db)
    dp_summary, _ = query_deal_progress_board(db, limit=2000)

    total = int(export["parcel_row_total"])
    brief_gap = export["parcels_missing_owner_outreach_brief"]
    miss_brief = int(brief_gap["count"])
    owner_target_count = int(brief_gap.get("target_count") or total)
    brief_count = max(0, owner_target_count - miss_brief)

    top_rows = query_parcels_scored_list(db, limit=5, sort=ENTITLEMENT)
    has_owner_brief_col = column_exists(db, "parcels", "owner_outreach_brief")
    top_parcels: list[dict[str, Any]] = []
    for row in top_rows:
        parcel = db.get(Parcel, row.parcel_id) if has_owner_brief_col else None
        top_parcels.append(
            {
                "parcel_id": str(row.parcel_id),
                "apn": row.apn,
                "county_fips": row.county_fips,
                "entitlement_score": row.entitlement_score,
                "strategic_score": row.strategic_score,
                "identification_score": row.identification_score,
                "lot_sqft": row.lot_sqft,
                "zoning_code": row.zoning_code,
                "has_outreach_brief": bool(parcel and parcel.owner_outreach_brief),
            },
        )

    counties_loaded = [
        {
            "county_fips": c["county_fips"],
            "county_name": c["county_name"],
            "parcels_in_db": c["parcels_in_db"],
            "priority_market": c.get("priority_market", False),
        }
        for c in scope["counties"]
        if c["parcels_in_db"] > 0
    ]

    return {
        "generated_at": datetime.now(UTC),
        "region_name": scope["region_name"],
        "state_name": scope["state_name"],
        "states_in_scope": scope.get("states_in_scope") or [],
        "primary_market_name": scope.get("primary_market_name", "Baltimore, Maryland"),
        "primary_market_state_fips": scope.get("primary_market_state_fips", "24"),
        "priority_county_fips": scope.get("priority_county_fips") or [],
        "parcels_in_priority_counties": scope.get("parcels_in_priority_counties", 0),
        "primary_metro_label": scope.get("primary_metro_label"),
        "pilot_county_count": scope["pilot_county_count"],
        "counties_with_ingested_parcels": scope["counties_with_ingested_parcels"],
        "counties_loaded": counties_loaded,
        "parcels_total": scoring["total_parcels"],
        "parcels_prescreen_qualified": export["parcels_prescreen_qualified"]["count"],
        "parcels_qualified_entitlement": scoring["qualified_count_entitlement"],
        "parcels_with_full_pipeline_scores": scoring["parcels_with_both_profiles_scored"],
        "parcels_with_owner_brief": brief_count,
        "parcels_pipeline_backlog": export["parcels_pipeline_funnel_backlog"]["count"],
        "qualified_floors": scoring["qualified_min_score"],
        "pipeline_runs_total": dp_summary.total_parcels,
        "pipeline_by_stage": dp_summary.by_status,
        "pipeline_by_step": dp_summary.by_step,
        "top_parcels": top_parcels,
        "sample_deliverables": build_platform_sample_deliverables(db),
    }
