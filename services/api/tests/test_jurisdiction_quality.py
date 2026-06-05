from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.jurisdiction_quality import ParcelQualityRecord, _summarize_records


def _record(
    *,
    county_fips: str = "53033",
    zoning_jurisdiction: str | None = "kent_city",
    complete: bool = True,
    entitlement_score: float | None = 80.0,
    created_at: datetime,
) -> ParcelQualityRecord:
    return ParcelQualityRecord(
        county_fips=county_fips,
        zoning_jurisdiction=zoning_jurisdiction,
        has_footprint=True,
        has_zoning=complete,
        has_lot_size=True,
        has_demand_distance=complete,
        has_poi_density=complete,
        has_owner_roll_name=complete,
        has_owner_outreach_brief=complete,
        has_identification_score=True,
        has_entitlement_score=entitlement_score is not None,
        has_strategic_score=complete,
        entitlement_score=entitlement_score,
        created_at=created_at,
    )


def test_jurisdiction_quality_prioritizes_stale_incomplete_market() -> None:
    now = datetime(2026, 6, 5, 12, tzinfo=UTC)
    summary = _summarize_records(
        [
            _record(created_at=now - timedelta(hours=2)),
            _record(
                county_fips="53061",
                zoning_jurisdiction=None,
                complete=False,
                entitlement_score=75.0,
                created_at=now - timedelta(days=8),
            ),
        ],
        now=now,
        entitlement_floor=60.0,
        limit=10,
    )

    assert summary["jurisdiction_count"] == 2
    assert summary["benchmark_quality_score"] == 100.0
    top = summary["rows"][0]
    assert top["county_fips"] == "53061"
    assert top["unresolved_core_gaps_older_24h"] == 1
    assert top["unresolved_core_gaps_older_7d"] == 1
    assert top["age_buckets"]["older_7d"] == 1
    assert top["missing_zoning"] == {"count": 1, "pct": 100.0}
    assert any("zoning overlay" in action for action in top["recommended_actions"])
    assert any("after 24h" in action for action in top["recommended_actions"])


def test_jurisdiction_quality_uses_benchmark_action_for_complete_qualified_market() -> None:
    now = datetime(2026, 6, 5, 12, tzinfo=UTC)
    summary = _summarize_records(
        [_record(created_at=now - timedelta(hours=1))],
        now=now,
        entitlement_floor=60.0,
        limit=10,
    )

    row = summary["rows"][0]
    assert row["quality_score"] == 100.0
    assert row["qualified_entitlement_count"] == 1
    assert row["recommended_actions"] == ["Use this jurisdiction as a benchmark playbook for weaker markets."]
