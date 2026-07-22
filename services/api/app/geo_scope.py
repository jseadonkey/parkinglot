"""Geographic scope principles + operator list performance budgets.

See ``config/geo_scope.yaml``. Prefer these helpers over hard-coding state FIPS
for timeouts, overfetch, aerial budgets, or vacancy SQL strategy.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings

_DEFAULT_LIST_PERF: dict[str, Any] = {
    "score_walk_timeout_ms": 45_000,
    "poi_seed_timeout_ms": 20_000,
    "poi_seed_skip_for_state_scope": True,
    "poi_seed_max_geography_parcels": 80_000,
    "vacant_overfetch_multiplier": 3,
    "vacant_overfetch_cap": 75,
    "aerial_enrich_max_rows": 40,
    "bare_overfetch_multiplier": 4,
    "bare_overfetch_cap": 200,
}

_DEFAULT_VACANCY_FLAGS: dict[str, Any] = {
    "true_values": ["Y", "1", "TRUE", "YES"],
    "no_improvement_keys": ["NO_IMPRV", "no_imprv", "NO_IMPROVEMENT", "UNIMPROVED"],
    "vacant_building_keys": ["VACIND", "vacind", "IS_VACANT", "VACANT_IND"],
}


def load_geo_scope(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path or get_settings().geo_scope_config_path)
    if not p.is_file():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


@lru_cache(maxsize=4)
def _cached_scope(path: str) -> dict[str, Any]:
    return load_geo_scope(path)


def list_performance(path: str | Path | None = None) -> dict[str, Any]:
    """Operator scored-list budgets (GLOBAL — all geos)."""
    cfg_path = str(path or get_settings().geo_scope_config_path)
    raw = _cached_scope(cfg_path)
    block = raw.get("list_performance") if isinstance(raw.get("list_performance"), dict) else {}
    out = dict(_DEFAULT_LIST_PERF)
    for key, default in _DEFAULT_LIST_PERF.items():
        if key not in block or block[key] is None:
            continue
        if isinstance(default, bool):
            out[key] = bool(block[key])
        elif isinstance(default, int):
            out[key] = int(block[key])
        else:
            out[key] = block[key]
    return out


def assessor_vacancy_flags(path: str | Path | None = None) -> dict[str, Any]:
    """Assessor vacant-flag key names shared across source adapters."""
    cfg_path = str(path or get_settings().geo_scope_config_path)
    raw = _cached_scope(cfg_path)
    block = raw.get("assessor_vacancy_flags") if isinstance(raw.get("assessor_vacancy_flags"), dict) else {}
    out = {k: list(v) for k, v in _DEFAULT_VACANCY_FLAGS.items()}
    for key in out:
        if isinstance(block.get(key), list) and block[key]:
            out[key] = [str(x) for x in block[key]]
    return out


def vacant_overfetch(cap: int, path: str | Path | None = None) -> int:
    perf = list_performance(path)
    mult = int(perf["vacant_overfetch_multiplier"])
    hard = int(perf["vacant_overfetch_cap"])
    return min(max(cap, 1) * mult, hard)


def aerial_enrich_max_rows(path: str | Path | None = None) -> int:
    return int(list_performance(path)["aerial_enrich_max_rows"])


def should_skip_poi_seed(
    *,
    state_scope: bool,
    geography_parcel_count: int | None = None,
    path: str | Path | None = None,
) -> bool:
    """True when POI density seed would be too expensive for this geography."""
    perf = list_performance(path)
    if state_scope and bool(perf.get("poi_seed_skip_for_state_scope", True)):
        return True
    max_n = int(perf.get("poi_seed_max_geography_parcels") or 80_000)
    if geography_parcel_count is not None and geography_parcel_count >= max_n:
        return True
    return False
