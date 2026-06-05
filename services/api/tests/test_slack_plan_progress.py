from __future__ import annotations

from unittest.mock import patch

from app.slack_digest import build_plan_progress_report_blocks


def _ready_summary() -> dict:
    return {
        "parcel_row_total": 100,
        "parcels_missing_score_identification": {"count": 0, "pct": 0.0},
        "parcels_missing_score_entitlement": {"count": 8, "pct": 8.0},
        "parcels_missing_score_strategic": {"count": 12, "pct": 12.0},
        "parcels_missing_distance_to_nearest_demand_m": {"count": 25, "pct": 25.0},
        "parcels_missing_zoning_code": {"count": 40, "pct": 40.0},
        "parcels_missing_owner_outreach_brief": {"count": 15, "pct": 15.0},
        "parcels_prescreen_qualified": {"count": 22, "pct": 22.0, "floor": 50.0},
        "parcels_pipeline_funnel_backlog": {"count": 9, "pct": 9.0, "floor": 50.0},
        "recommended_next_steps": [
            "Run Phase A refresh.",
            "Stage Phase B overlay.",
        ],
    }


def test_build_plan_progress_report_blocks_maps_readiness_to_phases() -> None:
    with patch("app.slack_digest.export_readiness_summary", return_value=_ready_summary()):
        blocks, fallback = build_plan_progress_report_blocks(object())  # type: ignore[arg-type]

    block_text = "\n".join(str(block) for block in blocks)
    assert "A-E plan progress" in fallback
    assert "A - scores, demand, readiness" in block_text
    assert "B - zoning overlay" in block_text
    assert "C - owner / outreach" in block_text
    assert "D - corner / richer demand" in block_text
    assert "E - county scale" in block_text
    assert "Run Phase A refresh." in block_text
    assert "Stage Phase B overlay." in block_text
