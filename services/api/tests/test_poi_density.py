from __future__ import annotations

from sqlalchemy.dialects import postgresql

from app.poi_density import (
    POI_DENSITY_CANDIDATE_MODE,
    select_poi_density_candidates,
)


def _compiled_sql(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ),
    )


def test_poi_density_selector_defaults_to_all_counties_qualified_only() -> None:
    sql = _compiled_sql(select_poi_density_candidates(limit=25))

    assert POI_DENSITY_CANDIDATE_MODE == "qualified_entitlement_and_strategic"
    assert "parcels.county_fips" not in sql
    assert "parcels.poi_commercial_count_400m IS NULL" in sql
    assert "parcels.footprint IS NOT NULL" in sql
    assert "parcel_scores.score_profile = 'entitlement'" in sql
    assert "parcel_scores.score_profile = 'strategic'" in sql
    assert ">= 70" in sql
    assert ">= 65" in sql


def test_poi_density_selector_can_scope_to_one_county() -> None:
    sql = _compiled_sql(select_poi_density_candidates(limit=25, county_fips="24510"))

    assert "parcels.county_fips = '24510'" in sql
    assert "parcel_scores.score_profile = 'entitlement'" in sql
    assert "parcel_scores.score_profile = 'strategic'" in sql
