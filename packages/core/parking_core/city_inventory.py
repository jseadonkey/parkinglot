from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CityInventoryEntry(BaseModel):
    geoid: str
    name: str
    basename: str
    slug: str
    state_fips: str
    place_fips: str
    lsadc: str
    funcstat: str
    jurisdiction_key: str
    boundary_path: str
    county_fips: list[str] = Field(default_factory=list)

    @field_validator("county_fips")
    @classmethod
    def _sort_counties(cls, value: list[str]) -> list[str]:
        return sorted({item.strip() for item in value if item and item.strip()})


class CityInventoryManifest(BaseModel):
    source_url: str
    state_fips: str
    generated_at: str
    place_count: int
    county_slice_count: int
    lsadc_counts: dict[str, int] = Field(default_factory=dict)
    entries: list[CityInventoryEntry] = Field(default_factory=list)

    def entry_by_geoid(self) -> dict[str, CityInventoryEntry]:
        return {entry.geoid: entry for entry in self.entries}

    def jurisdiction_keys(self) -> set[str]:
        return {entry.jurisdiction_key for entry in self.entries}


def slugify_place_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "unknown"


def disambiguate_slugs(entries: list[dict[str, Any]]) -> dict[str, str]:
    """Return stable slugs; duplicate basenames get a short place-code suffix."""

    base_slugs = {str(entry["geoid"]): slugify_place_name(str(entry["basename"])) for entry in entries}
    counts: dict[str, int] = {}
    for slug in base_slugs.values():
        counts[slug] = counts.get(slug, 0) + 1
    out: dict[str, str] = {}
    for geoid, slug in base_slugs.items():
        if counts[slug] == 1:
            out[geoid] = slug
        else:
            out[geoid] = f"{slug}_{geoid[-5:]}"
    return out


def load_city_inventory_manifest(path: str | Path) -> CityInventoryManifest:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"Invalid city inventory manifest (expected object): {path}"
        raise TypeError(msg)
    return CityInventoryManifest.model_validate(raw)
