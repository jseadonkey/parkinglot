from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def normalize_zone_code(code: str | None) -> str:
    return (code or "").strip().upper()


# King County CURRZONE overlay suffixes (longest match first in lookup).
_ZONE_SUFFIX_FALLBACKS = ("-P-SO", "-SO", "-P", "-DPA")


def zone_lookup_candidates(zoning_code: str | None) -> list[str]:
    """Exact zone first, then progressively shorter base codes for overlay suffixes."""
    z_norm = normalize_zone_code(zoning_code)
    if not z_norm:
        return []
    candidates = [z_norm]
    for suffix in _ZONE_SUFFIX_FALLBACKS:
        if z_norm.endswith(suffix):
            base = z_norm[: -len(suffix)]
            if base and base not in candidates:
                candidates.append(base)
    return candidates


def lookup_zone_entry(zones: dict[str, Any], zoning_code: str | None) -> Any | None:
    if not isinstance(zones, dict):
        return None
    for candidate in zone_lookup_candidates(zoning_code):
        entry = zones.get(candidate)
        if entry is not None:
            return entry
    raw = (zoning_code or "").strip()
    if raw:
        return zones.get(raw)
    return None


def load_zoning_rules(path: Path | None) -> dict[str, Any]:
    """Load rules YAML; empty dict-shaped fallback if path missing or unreadable."""
    if path is None or not path.is_file():
        return {"default_when_unknown": False, "jurisdictions": {}}
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        return {"default_when_unknown": False, "jurisdictions": {}}
    return data


def effective_zoning_rules_path(explicit: Path | None = None) -> Path | None:
    """Resolve which rules file to use: explicit path, then env, then Docker mount, then cwd default."""
    if explicit is not None:
        return explicit if explicit.is_file() else None

    env = (os.environ.get("ZONING_RULES_PATH") or "").strip()
    if env:
        p = Path(env)
        return p if p.is_file() else None

    docker = Path("/app/data/zoning/wa/kent_king_surface_parking_rules.yaml")
    if docker.is_file():
        return docker

    local = Path.cwd() / "data/zoning/wa/kent_king_surface_parking_rules.yaml"
    if local.is_file():
        return local

    return None


def resolve_surface_parking(
    zoning_code: str | None,
    jurisdiction_key: str | None,
    explicit_override: bool | None,
    rules: dict[str, Any],
) -> bool:
    """Apply explicit GeoJSON override if provided; else YAML lookup; else default_when_unknown."""
    if explicit_override is not None:
        return bool(explicit_override)

    default = bool(rules.get("default_when_unknown", False))
    jk = (jurisdiction_key or "").strip().lower()
    if not jk or zoning_code is None or str(zoning_code).strip() == "":
        return default

    jurisdictions = rules.get("jurisdictions") or {}
    block = jurisdictions.get(jk)
    if not isinstance(block, dict):
        return default

    zones = block.get("zones") or {}
    entry = lookup_zone_entry(zones if isinstance(zones, dict) else {}, str(zoning_code))
    if entry is None:
        return default

    if isinstance(entry, bool):
        return entry

    if isinstance(entry, dict) and "allows_surface_parking" in entry:
        return bool(entry["allows_surface_parking"])

    return default
