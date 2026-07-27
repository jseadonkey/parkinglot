from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.parcel_scored_list import ParcelScoredRowData, query_parcels_scored_list
from app.routers.internal import parcels_scored_list


def test_query_parcels_scored_list_min_entitlement_filter() -> None:
    db = MagicMock()
    db.execute.return_value.all.return_value = []
    out = query_parcels_scored_list(db, limit=10, min_entitlement_score=70.0)
    assert out == []
    assert db.execute.called


@patch("app.routers.internal.attach_revenue_summaries", return_value={})
@patch("app.routers.internal.query_parcels_scored_list")
@patch("app.routers.internal.load_pilot_config")
def test_scored_list_attaches_revenue_for_visible_rows_below_floor(
    mock_pilot_cfg,
    mock_query,
    mock_attach,
) -> None:
    """List revenue is for the visible shortlist, not entitlement≥floor only."""
    from datetime import UTC, datetime

    mock_pilot_cfg.return_value.scoring.qualified_min_score = 70.0
    pid = __import__("uuid").uuid4()
    mock_query.return_value = [
        ParcelScoredRowData(
            parcel_id=pid,
            apn="TEST-LOW",
            county_fips="53001",
            zoning_code="C-1",
            lot_sqft=12_000.0,
            zoning_principal_use_symbol="P",
            zoning_entitlement_tier="permitted",
            entitlement_score=55.0,
            strategic_score=None,
            identification_score=55.0,
            combined_score=55.0,
            created_at=datetime.now(UTC),
        ),
    ]
    mock_attach.return_value = {
        str(pid): {
            "revenue_available": True,
            "monthly_gross_usd": 4_500.0,
            "stalls_estimated": 28,
            "demand_occupancy_factor": 0.92,
        },
    }
    db = MagicMock()
    resp = parcels_scored_list(
        limit=25,
        sort="combined",
        county_fips=None,
        state_fips="53",
        zoning_tier=None,
        suitability="vacant",
        prefer_paved=True,
        surface=None,
        qualified_only=False,
        include_revenue=True,
        revenue_max_rows=25,
        min_entitlement_score=None,
        db=db,
    )
    assert resp.revenue_rows_computed == 1
    mock_attach.assert_called_once()
    assert mock_attach.call_args.kwargs["parcel_ids"] == [pid]
    assert resp.rows[0].revenue is not None
    assert resp.rows[0].revenue.monthly_gross_usd == 4_500.0
