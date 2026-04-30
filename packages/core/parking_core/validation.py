"""Shared validation helpers."""

from parking_core.pilot import PilotConfig


def assert_pilot_county(parcel_county_fips: str, pilot: PilotConfig) -> None:
    allowed = set(pilot.region.county_fips)
    if allowed and parcel_county_fips not in allowed:
        msg = f"Parcel county {parcel_county_fips} not in pilot counties {sorted(allowed)}"
        raise ValueError(msg)
