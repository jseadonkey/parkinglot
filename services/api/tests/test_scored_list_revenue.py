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
def test_scored_list_attaches_revenue_for_qualified_rows(
    mock_pilot_cfg,
    mock_query,
    mock_attach,
) -> None:
    from datetime import UTC, datetime

    mock_pilot_cfg.return_value.scoring.qualified_min_score = 70.0
    pid = __import__("uuid").uuid4()
    mock_query.return_value = [
        ParcelScoredRowData(
            parcel_id=pid,
            apn="TEST-1",
            county_fips="24510",
            zoning_code="I-2",
            lot_sqft=20_000.0,
            zoning_principal_use_symbol="P",
            zoning_entitlement_tier="permitted",
            entitlement_score=75.0,
            strategic_score=None,
            identification_score=65.0,
            combined_score=70.0,
            created_at=datetime.now(UTC),
        ),
    ]
    mock_attach.return_value = {
        str(pid): {
            "revenue_available": True,
            "monthly_gross_usd": 12_000.0,
            "stalls_estimated": 40,
            "hourly_rate_weighted_usd": 9.5,
        },
    }
    db = MagicMock()
    resp = parcels_scored_list(
        limit=50,
        sort="combined",
        county_fips=None,
        state_fips=None,
        zoning_tier=None,
        qualified_only=True,
        include_revenue=True,
        revenue_max_rows=200,
        min_entitlement_score=None,
        db=db,
    )
    assert resp.row_count == 1
    assert resp.revenue_rows_computed == 1
    assert resp.rows[0].revenue is not None
    assert resp.rows[0].revenue.revenue_available is True
    assert resp.rows[0].revenue.monthly_gross_usd == 12_000.0
