"""Normalize situs and mailing addresses from county-specific GIS property names."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_MAPS_MARKER = Path("data") / "jurisdictions" / "wa" / "address_field_maps.yaml"


def _repo_root() -> Path:
    """Find repo root whether running from source, site-packages (CI), or /app (Docker)."""
    here = Path(__file__).resolve()
    for start in (here, Path.cwd().resolve()):
        for parent in (start, *start.parents):
            if (parent / _MAPS_MARKER).is_file():
                return parent
    env_root = (os.environ.get("PARKINGLOT_ROOT") or os.environ.get("REPO_ROOT") or "").strip()
    if env_root:
        candidate = Path(env_root).resolve()
        if (candidate / _MAPS_MARKER).is_file():
            return candidate
    return here.parents[3]


def _default_maps_path() -> Path:
    root = _repo_root()
    candidates = (
        root / "data" / "jurisdictions" / "wa" / "address_field_maps.yaml",
        Path("/app/data/jurisdictions/wa/address_field_maps.yaml"),
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]

_ZIP_ONLY = re.compile(r"^\d{5}(?:-\d{4})?$")
_STREET_HINT = re.compile(
    r"\b(ST|STREET|AVE|AVENUE|DR|DRIVE|RD|ROAD|BLVD|WAY|LN|LANE|CT|COURT|PL|PLACE|HWY)\b",
    re.I,
)
_NON_SITUS_ROAD = re.compile(
    r"\b(trail|freeway|railway|railroad|interurban|bike\s*path)\b",
    re.I,
)

ADDRESS_KEYS = (
    "PROPERTY_ADDRESS",
    "property_address",
    "SITUS_ADDRESS",
    "situs_address",
    "ADDR_FULL",
    "addr_full",
    "FULLADDR",
    "VISIT_ADDRESS",
    "visit_address",
    "MAP_ADDRESS",
    "map_address",
)


def _strip_str(val: Any) -> str | None:
    if val is None:
        return None
    text = str(val).strip()
    return text or None


def looks_like_street(value: str | None) -> bool:
    text = (value or "").strip()
    if not text or _ZIP_ONLY.match(text):
        return False
    if _NON_SITUS_ROAD.search(text):
        return False
    if re.search(r"\d", text):
        return True
    return bool(_STREET_HINT.search(text))


def has_usable_situs(props: dict[str, Any]) -> bool:
    for key in ADDRESS_KEYS:
        text = _strip_str(props.get(key))
        if text and looks_like_street(text):
            return True
    line1 = _strip_str(props.get("SITUS_LINE1") or props.get("situs_line1") or props.get("LOC_STREET"))
    city = _strip_str(props.get("SITUS_CITY") or props.get("situs_city") or props.get("SITUS_CITY_NM"))
    if line1 and looks_like_street(line1) and city:
        return True
    return False


def _first_prop(props: dict[str, Any], keys: list[str] | tuple[str, ...]) -> str | None:
    for key in keys:
        text = _strip_str(props.get(key))
        if text:
            return text
    return None


def _copy_if_absent(props: dict[str, Any], key: str, value: str | None) -> None:
    if not value:
        return
    if not _strip_str(props.get(key)):
        props[key] = value


@lru_cache(maxsize=4)
def _load_maps(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _resolve_county_map(maps: dict[str, Any], county_fips: str) -> dict[str, Any] | None:
    cf = (county_fips or "").strip()
    if not cf:
        return None
    counties = maps.get("counties")
    if not isinstance(counties, dict):
        return None
    entry = counties.get(cf)
    if not isinstance(entry, dict):
        if cf.startswith("53"):
            entry = {"inherit": "default_wa_watech"}
        else:
            return None
    inherit = entry.get("inherit")
    base_key = inherit if isinstance(inherit, str) else None
    base = maps.get(base_key) if base_key else {}
    if not isinstance(base, dict):
        base = {}
    merged: dict[str, Any] = {**base, **{k: v for k, v in entry.items() if k != "inherit"}}
    return merged


def normalize_parcel_address_props(
    props: dict[str, Any],
    *,
    county_fips: str | None = None,
    maps_path: Path | None = None,
) -> bool:
    """Map county-specific situs/mailing columns to normalized keys. Returns True if situs was written."""
    cf = str(county_fips or props.get("COUNTY_FIPS") or props.get("county_fips") or "").strip()
    if cf == "24510":
        return False

    path = maps_path or _default_maps_path()
    maps = _load_maps(str(path.resolve()))
    county_map = _resolve_county_map(maps, cf)
    if not county_map:
        return False

    existing_canonical = _strip_str(props.get("PROPERTY_ADDRESS"))
    if existing_canonical and looks_like_street(existing_canonical):
        return False

    street = _first_prop(props, county_map.get("situs_street") or ())
    if not street:
        street = _strip_str(props.get("SITUS_ADDRESS") or props.get("situs_address"))
    if street and not looks_like_street(street):
        street = None

    city = _first_prop(props, county_map.get("situs_city") or ())
    state = (_first_prop(props, county_map.get("situs_state") or ()) or "WA").upper()[:2]
    zip_code = _first_prop(props, county_map.get("situs_zip") or ())
    if zip_code:
        zip_code = zip_code[:5]

    wrote = False
    if street and looks_like_street(street):
        _copy_if_absent(props, "SITUS_ADDRESS", street)
        _copy_if_absent(props, "PROPERTY_ADDRESS", street)
        _copy_if_absent(props, "ADDR_FULL", street)
        wrote = True
    if city:
        _copy_if_absent(props, "SITUS_CITY", city)
        _copy_if_absent(props, "SITUS_CITY_NM", city)
    if state:
        _copy_if_absent(props, "SITUS_STATE", state)
    if zip_code:
        _copy_if_absent(props, "SITUS_ZIP", zip_code)
        _copy_if_absent(props, "SITUS_ZIP_NR", zip_code)

    mailing = _first_prop(props, county_map.get("mailing") or ())
    if mailing:
        _copy_if_absent(props, "MAILING_ADDRESS", mailing)
        _copy_if_absent(props, "MAIL_ADDR", mailing)

    owner = _first_prop(props, county_map.get("owner") or ())
    if owner:
        _copy_if_absent(props, "OWNER_NAME", owner)

    if wrote or mailing or owner:
        source = str(county_map.get("address_source") or "address_normalize")
        if not _strip_str(props.get("ADDRESS_SOURCE")):
            props["ADDRESS_SOURCE"] = source
        props.setdefault("ADDRESS_NORMALIZED", True)
    return wrote
