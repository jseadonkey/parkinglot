from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .paths import SOURCE_CHAINS


def _load_chains(path: Path = SOURCE_CHAINS) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def chain_key_for_county(county_fips: str) -> str:
    cfg = _load_chains()
    overrides = cfg.get("county_overrides") if isinstance(cfg.get("county_overrides"), dict) else {}
    return str(overrides.get(county_fips.strip()) or "default_wa_county")


def source_chain_for_county(county_fips: str) -> list[str]:
    cfg = _load_chains()
    chains = cfg.get("chains") if isinstance(cfg.get("chains"), dict) else {}
    key = chain_key_for_county(county_fips)
    block = chains.get(key) if isinstance(chains.get(key), dict) else chains.get("default_wa_county")
    if not isinstance(block, dict):
        return []
    sources = block.get("sources")
    return [str(s) for s in sources] if isinstance(sources, list) else []


def advance_source(county_fips: str, current_source_id: str | None) -> tuple[str | None, bool]:
    """Return (next_source_id, rotated). None when chain exhausted."""
    chain = source_chain_for_county(county_fips)
    if not chain:
        return None, False
    if not current_source_id:
        return chain[0], False
    try:
        idx = chain.index(current_source_id)
    except ValueError:
        return chain[0], True
    if idx + 1 >= len(chain):
        return None, False
    return chain[idx + 1], True
