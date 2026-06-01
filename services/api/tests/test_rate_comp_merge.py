from __future__ import annotations

from parking_core.pilot import ParkingRateCompObservation
from parking_scoring.engine import _merge_rate_comp_sequences


def test_merge_rate_comp_sequences_dedupes_same_lat_lon_name() -> None:
    a = ParkingRateCompObservation(name="Lot A", lat=47.6062, lon=-122.3321, hourly_mid_usd=10.0)
    b = ParkingRateCompObservation(name="Lot A", lat=47.6062, lon=-122.3321, hourly_mid_usd=99.0)
    out = _merge_rate_comp_sequences([a], [b])
    assert len(out) == 1
    assert out[0].hourly_mid_usd == 10.0


def test_merge_rate_comp_sequences_keeps_distinct_comps() -> None:
    db = ParkingRateCompObservation(
        name="DB comp",
        lat=47.61,
        lon=-122.33,
        hourly_mid_usd=12.0,
        origin="database",
    )
    pilot = ParkingRateCompObservation(name="Pilot comp", lat=47.62, lon=-122.34, hourly_mid_usd=14.0)
    out = _merge_rate_comp_sequences([db], [pilot])
    assert len(out) == 2
