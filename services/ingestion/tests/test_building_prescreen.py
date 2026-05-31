"""Building value prescreen helpers."""

from __future__ import annotations

from parking_ingestion.building_prescreen import building_value_prescreen_pass, building_value_share


def test_pass_when_values_missing() -> None:
    assert building_value_prescreen_pass({})


def test_reject_high_building_share() -> None:
    props = {"VALUE_LAND": 100_000, "VALUE_BLDG": 400_000}
    assert building_value_share(props) == 0.8
    assert not building_value_prescreen_pass(props, max_building_share=0.70)


def test_pass_vacant_land_dominant() -> None:
    props = {"VALUE_LAND": 300_000, "VALUE_BLDG": 50_000}
    assert building_value_prescreen_pass(props, max_building_share=0.70)
