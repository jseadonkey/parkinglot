from __future__ import annotations

from app.schemas import ExportReadinessResponse


def _gap(count: int = 0, pct: float = 0.0) -> dict[str, float | int]:
    return {"count": count, "pct": pct}


def test_export_readiness_response_serializes_poi_candidate_stats() -> None:
    response = ExportReadinessResponse(
        parcel_row_total=100,
        parcels_missing_footprint=_gap(),
        parcels_missing_zoning_code=_gap(),
        parcels_missing_lot_sqft=_gap(),
        parcels_missing_distance_to_nearest_demand_m=_gap(),
        parcels_missing_poi_commercial_count_400m={
            "count": 3,
            "pct": 30.0,
            "candidate_mode": "qualified_entitlement_and_strategic",
        },
        parcels_poi_density_candidates={
            "count": 10,
            "pct": 10.0,
            "candidate_mode": "qualified_entitlement_and_strategic",
            "entitlement_floor": 70.0,
            "strategic_floor": 65.0,
        },
        parcels_missing_poi_commercial_count_400m_all=_gap(80, 80.0),
        parcels_missing_score_identification=_gap(),
        parcels_missing_score_entitlement=_gap(),
        parcels_missing_score_strategic=_gap(),
        parcels_missing_entitlement_or_strategic=_gap(),
        parcels_prescreen_qualified={"count": 20, "pct": 20.0, "floor": 60.0},
        parcels_pipeline_funnel_backlog={"count": 5, "pct": 5.0, "floor": 60.0},
        parcels_ruled_out_by_prescreen={"count": 1, "pct": 1.0, "floor": 60.0},
        parcels_ruled_out_at_atlas={"count": 2, "pct": 2.0, "floor": 70.0},
        parcels_owner_outreach_targets={
            "count": 4,
            "pct": 4.0,
            "entitlement_floor": 85.0,
            "strategic_floor": 80.0,
        },
        parcels_missing_baltimore_candidate_street_address={
            "count": 3,
            "pct": 15.0,
            "target_count": 20,
            "floor": 60.0,
        },
        parcels_missing_owner_outreach_brief={
            "count": 1,
            "pct": 25.0,
            "target_count": 4,
            "entitlement_floor": 85.0,
            "strategic_floor": 80.0,
        },
        parcels_prescreen_qualified_missing_owner_outreach_brief={
            "count": 1,
            "pct": 5.0,
            "floor": 60.0,
        },
        recommended_next_steps=[],
    )

    serialized = response.model_dump()
    assert serialized["parcels_missing_poi_commercial_count_400m"]["count"] == 3
    assert serialized["parcels_poi_density_candidates"]["count"] == 10
    assert serialized["parcels_missing_poi_commercial_count_400m_all"]["count"] == 80
    assert serialized["parcels_missing_baltimore_candidate_street_address"]["target_count"] == 20
