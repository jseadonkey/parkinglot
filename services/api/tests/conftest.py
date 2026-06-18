"""Local pytest hooks — ensure zoning rules YAML resolves outside Docker."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RULE_PATHS = [
    _REPO_ROOT / "data/zoning/wa/kent_king_surface_parking_rules.yaml",
    _REPO_ROOT / "data/zoning/wa/wa_county_surface_parking_rules.yaml",
    _REPO_ROOT / "data/zoning/md/baltimore_city_surface_parking_rules.yaml",
]
_rules = [str(p) for p in _RULE_PATHS if p.is_file()]
if _rules:
    os.environ.setdefault("ZONING_RULES_PATH", ",".join(_rules))
for _env_name, _rel in (
    ("PILOT_CONFIG_PATH", "config/pilot.yaml"),
    ("PILOT_STRATEGIC_CONFIG_PATH", "config/pilot_strategic.yaml"),
    ("PILOT_IDENTIFICATION_CONFIG_PATH", "config/pilot_identification.yaml"),
    ("GEO_MARKETS_CONFIG_PATH", "config/geo_markets.yaml"),
):
    _path = _REPO_ROOT / _rel
    if _path.is_file():
        os.environ.setdefault(_env_name, str(_path))
