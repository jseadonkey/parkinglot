from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# County FIPS → zoning_rules.yaml jurisdiction key (ingest when overlay omits ZONING_JURISDICTION).
COUNTY_FIPS_TO_ZONING_JURISDICTION: dict[str, str] = {
    "24510": "baltimore_city",
}


def normalize_zone_code(code: str | None) -> str:
    return (code or "").strip().upper()


def infer_zoning_jurisdiction(county_fips: str, explicit_jurisdiction: str | None) -> str | None:
    """Default jurisdiction from county when spatial join did not set ZONING_JURISDICTION."""
    if explicit_jurisdiction is not None and str(explicit_jurisdiction).strip():
        return str(explicit_jurisdiction).strip()
    cf = (county_fips or "").strip()
    return COUNTY_FIPS_TO_ZONING_JURISDICTION.get(cf)


def load_zoning_rules(path: Path | None) -> dict[str, Any]:
    """Load rules YAML; empty dict-shaped fallback if path missing or unreadable."""
    if path is None or not path.is_file():
        return {"default_when_unknown": False, "jurisdictions": {}}
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        return {"default_when_unknown": False, "jurisdictions": {}}
    return data


def merge_zoning_rules(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Merge jurisdiction blocks; later paths override zone entries for the same jurisdiction."""
    out: dict[str, Any] = {
        "default_when_unknown": bool(base.get("default_when_unknown", False))
        or bool(extra.get("default_when_unknown", False)),
        "jurisdictions": dict(base.get("jurisdictions") or {}),
    }
    for jkey, jblock in (extra.get("jurisdictions") or {}).items():
        if not isinstance(jblock, dict):
            continue
        existing = out["jurisdictions"].get(jkey)
        if not isinstance(existing, dict):
            out["jurisdictions"][jkey] = dict(jblock)
            continue
        merged_block = dict(existing)
        ez = existing.get("zones") if isinstance(existing.get("zones"), dict) else {}
        nz = jblock.get("zones") if isinstance(jblock.get("zones"), dict) else {}
        merged_block["zones"] = {**ez, **nz}
        for k in ("source_url", "ordinance_ref", "note"):
            if jblock.get(k):
                merged_block[k] = jblock[k]
        out["jurisdictions"][jkey] = merged_block
    return out


def zoning_rules_search_paths(explicit: Path | None = None) -> list[Path]:
    """Paths to merge (explicit, env comma-list, then WA + MD defaults)."""
    seen: set[str] = set()
    paths: list[Path] = []

    def add(p: Path) -> None:
        key = str(p.resolve()) if p.is_file() else str(p)
        if p.is_file() and key not in seen:
            seen.add(key)
            paths.append(p)

    if explicit is not None:
        add(explicit)

    env = (os.environ.get("ZONING_RULES_PATH") or "").strip()
    if env:
        for part in env.split(","):
            add(Path(part.strip()))

    for candidate in (
        Path("/app/data/zoning/wa/kent_king_surface_parking_rules.yaml"),
        Path("/app/data/zoning/md/baltimore_city_surface_parking_rules.yaml"),
        Path.cwd() / "data/zoning/wa/kent_king_surface_parking_rules.yaml",
        Path.cwd() / "data/zoning/md/baltimore_city_surface_parking_rules.yaml",
    ):
        add(candidate)

    return paths


def load_effective_zoning_rules(explicit: Path | None = None) -> dict[str, Any]:
    """Load and merge all applicable zoning rule files (multi-state)."""
    merged: dict[str, Any] = {"default_when_unknown": False, "jurisdictions": {}}
    found = False
    for p in zoning_rules_search_paths(explicit):
        merged = merge_zoning_rules(merged, load_zoning_rules(p))
        found = True
    if not found:
        return {"default_when_unknown": False, "jurisdictions": {}}
    return merged


def effective_zoning_rules_path(explicit: Path | None = None) -> Path | None:
    """First resolved rules file (legacy); prefer ``load_effective_zoning_rules`` for ingest."""
    paths = zoning_rules_search_paths(explicit)
    return paths[0] if paths else None


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

    z_norm = normalize_zone_code(str(zoning_code))
    jurisdictions = rules.get("jurisdictions") or {}
    block = jurisdictions.get(jk)
    if not isinstance(block, dict):
        return default

    zones = block.get("zones") or {}
    if not isinstance(zones, dict):
        return default

    entry = zones.get(z_norm)
    if entry is None:
        entry = zones.get(str(zoning_code).strip())

    if entry is None:
        return default

    if isinstance(entry, bool):
        return entry

    if isinstance(entry, dict) and "allows_surface_parking" in entry:
        return bool(entry["allows_surface_parking"])

    return default
