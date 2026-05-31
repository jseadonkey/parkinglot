"""Parking comp entitlement gate."""

from __future__ import annotations

import uuid

from app.db.models import Parcel
from app.parking_comp_gate import parcel_meets_parking_comp_gate
from parking_core.pilot import load_pilot_config
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PILOT = REPO / "config" / "pilot.yaml"


def _parcel(**kwargs) -> Parcel:
    base = dict(
        id=uuid.uuid4(),
        apn="TEST",
        county_fips="53033",
        zoning_allows_surface_parking=True,
        raw_properties={"VALUE_LAND": 200_000, "VALUE_BLDG": 50_000},
    )
    base.update(kwargs)
    return Parcel(**base)


def test_gate_requires_entitlement_floor() -> None:
    pilot = load_pilot_config(PILOT)
    assert not parcel_meets_parking_comp_gate(_parcel(), 54.0, pilot)
    assert parcel_meets_parking_comp_gate(_parcel(), 55.0, pilot)


def test_gate_requires_surface_zoning() -> None:
    pilot = load_pilot_config(PILOT)
    p = _parcel(zoning_allows_surface_parking=False)
    assert not parcel_meets_parking_comp_gate(p, 60.0, pilot)


def test_gate_rejects_built_out() -> None:
    pilot = load_pilot_config(PILOT)
    p = _parcel(raw_properties={"VALUE_LAND": 50_000, "VALUE_BLDG": 450_000})
    assert not parcel_meets_parking_comp_gate(p, 60.0, pilot)
