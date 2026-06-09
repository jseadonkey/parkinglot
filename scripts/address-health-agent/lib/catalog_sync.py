"""Update data files when the agent rotates to a new address source (no scraper rewrites)."""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .paths import FIELD_MAPS, SOURCE_CATALOG


def _read_catalog(path: Path = SOURCE_CATALOG) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_catalog(rows: list[dict[str, str]], path: Path = SOURCE_CATALOG) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def catalog_row_for_source(source_id: str) -> dict[str, str] | None:
    for row in _read_catalog():
        if (row.get("source_id") or "").strip() == source_id:
            return row
    return None


def apply_source_rotation(county_fips: str, new_source_id: str) -> dict[str, Any]:
    """Point county field maps at the new catalog source; mark catalog active."""
    row = catalog_row_for_source(new_source_id)
    out: dict[str, Any] = {
        "county_fips": county_fips,
        "new_source_id": new_source_id,
        "catalog_updated": False,
        "field_maps_updated": False,
    }
    if not row:
        out["warning"] = f"source_id {new_source_id} not in catalog — add connector before ingest"
        return out

    today = datetime.now(timezone.utc).date().isoformat()
    rows = _read_catalog()
    for r in rows:
        if (r.get("source_id") or "").strip() == new_source_id:
            r["address_source_status"] = "active"
            r["last_checked_at"] = today
            out["catalog_updated"] = True
        elif (r.get("county_fips") or "").strip() == county_fips and r.get("source_type") in (
            "assessor_value",
            "parcel",
        ):
            if (r.get("source_id") or "").strip() != new_source_id:
                prev = (r.get("address_source_status") or "").strip()
                if prev == "active":
                    r["address_source_status"] = "degraded"
    if out["catalog_updated"]:
        _write_catalog(rows)

    if not FIELD_MAPS.is_file():
        return out

    raw = yaml.safe_load(FIELD_MAPS.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return out
    counties = raw.setdefault("counties", {})
    if not isinstance(counties, dict):
        return out

    entry = counties.get(county_fips)
    if not isinstance(entry, dict):
        entry = {"inherit": "default_wa_watech"}
    entry = dict(entry)
    entry["address_source"] = new_source_id
    situs_fields = (row.get("address_situs_fields") or "").strip()
    if situs_fields and situs_fields != "TBD":
        entry["situs_street"] = [f.strip() for f in re.split(r"[;,]", situs_fields) if f.strip()]
    entry["rotated_at"] = today
    counties[county_fips] = entry
    FIELD_MAPS.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    out["field_maps_updated"] = True
    return out
