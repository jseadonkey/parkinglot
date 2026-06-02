from __future__ import annotations

from pathlib import Path

import yaml

from app.pilot_scope import COUNTY_DISPLAY_NAMES


def test_county_display_names_cover_pilot_yaml_counties() -> None:
    root = Path(__file__).resolve().parents[3]
    pilot = yaml.safe_load((root / "config" / "pilot.yaml").read_text(encoding="utf-8"))
    for fips in pilot["region"]["county_fips"]:
        assert fips in COUNTY_DISPLAY_NAMES, fips
