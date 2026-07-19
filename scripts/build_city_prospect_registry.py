#!/usr/bin/env python3
"""Build per-city prospect data-source registry + demand generators (fully automated).

For every incorporated place (and unincorporated county bucket) already in Postgres:

1. Parcel geometry/APN     → WaTech (WA) or Baltimore EGIS (MD)
2. Zoning code/class       → WAZA and/or county Phase B overlay (from config)
3. Vacancy/suitability     → assessor VALUE_BLDG/VALUE_LAND on parcel (WA);
                             Baltimore uses city assessor fields in raw_properties
4. Demand proximity        → auto city-centroid demand generator

Writes:
  - data/jurisdictions/city_prospect_sources.csv
  - config/demand_generators_wa_cities.yaml  (also includes Baltimore City)

Safe to re-run; deterministic output ordered by county then city.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

import yaml

REPO = Path(os.environ.get("CITY_REGISTRY_REPO", Path(__file__).resolve().parents[1]))
OUT_CSV = Path(os.environ.get("CITY_REGISTRY_CSV", str(REPO / "data" / "jurisdictions" / "city_prospect_sources.csv")))
OUT_DEMAND = Path(os.environ.get("CITY_REGISTRY_DEMAND", str(REPO / "config" / "demand_generators_wa_cities.yaml")))
PHASE_B = REPO / "config" / "wa_phase_b_rollout.yaml"
SOURCE_CATALOG = REPO / "data" / "jurisdictions" / "wa" / "source_catalog.csv"

# Minimum parcels to emit a demand POI (tiny place-names / noise filtered).
MIN_PARCELS_FOR_DEMAND = 25


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return s or "unknown"


def _load_waza_counties() -> set[str]:
    """Counties that have a WAZA zoning_sources block in Phase B config."""
    if not PHASE_B.is_file():
        return set()
    raw = yaml.safe_load(PHASE_B.read_text(encoding="utf-8")) or {}
    out: set[str] = set()
    for cf, block in (raw.get("counties") or {}).items():
        if not isinstance(block, dict):
            continue
        for src in block.get("zoning_sources") or []:
            if not isinstance(src, dict):
                continue
            blob = f"{src.get('source_id','')} {src.get('label','')} {src.get('layer_url','')}".lower()
            if "waza" in blob:
                out.add(str(cf))
                break
    return out


def _load_phase_b_zoning_counties() -> dict[str, str]:
    """county_fips → primary zoning source label from Phase B config."""
    if not PHASE_B.is_file():
        return {}
    raw = yaml.safe_load(PHASE_B.read_text(encoding="utf-8")) or {}
    counties = raw.get("counties") or {}
    out: dict[str, str] = {}
    for cf, block in counties.items():
        if not isinstance(block, dict):
            continue
        sources = block.get("zoning_sources") or []
        if not sources:
            continue
        labels = []
        for src in sources:
            if isinstance(src, dict):
                labels.append(str(src.get("source_id") or src.get("label") or "overlay"))
        out[str(cf)] = ",".join(labels) if labels else "county_overlay"
    return out


def _catalog_urls() -> dict[str, str]:
    """jurisdiction-ish key → source_url from source_catalog.csv."""
    if not SOURCE_CATALOG.is_file():
        return {}
    out: dict[str, str] = {}
    with SOURCE_CATALOG.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            jid = (row.get("jurisdiction_id") or "").strip()
            url = (row.get("source_url") or "").strip()
            stype = (row.get("source_type") or "").strip()
            if jid and url and stype == "zoning":
                out[jid] = url
    return out


def _session():
    # Prefer running inside API container; fall back to local DATABASE_URL.
    sys.path.insert(0, str(REPO / "services" / "api"))
    from app.db.session import SessionLocal  # noqa: WPS433

    return SessionLocal()


def fetch_city_rows(db) -> list[dict]:
    """One row per (county_fips, city_name) with centroid + WAZA coverage."""
    from sqlalchemy import text

    # Centroid via average of parcel centroids — chunked by using ST_Centroid once
    # on a representative sample would be faster, but full avg is OK overnight;
    # for interactive runs we use PointOnSurface of a random subset via DISTINCT ON.
    sql = text(
        """
        WITH place_parcels AS (
          SELECT
            county_fips,
            CASE
              WHEN county_fips = '24510' THEN 'Baltimore'
              ELSE COALESCE(NULLIF(TRIM(incorporated_place_name), ''), '(unincorporated)')
            END AS city_name,
            ST_X(ST_PointOnSurface(footprint::geometry)) AS lon,
            ST_Y(ST_PointOnSurface(footprint::geometry)) AS lat,
            CASE WHEN raw_properties ? 'WAZAZoneGeneral' THEN 1 ELSE 0 END AS has_waza,
            CASE WHEN zoning_code IS NOT NULL AND zoning_code <> '' THEN 1 ELSE 0 END AS has_zoning,
            CASE WHEN raw_properties ? 'VALUE_BLDG' THEN 1 ELSE 0 END AS has_bldg_value,
            raw_properties->>'ZONING_JURISDICTION' AS zoning_jurisdiction
          FROM parcels
          WHERE footprint IS NOT NULL
        )
        SELECT
          county_fips,
          city_name,
          COUNT(*)::int AS parcel_count,
          AVG(lat) AS lat,
          AVG(lon) AS lon,
          SUM(has_waza)::int AS waza_parcels,
          SUM(has_zoning)::int AS zoned_parcels,
          SUM(has_bldg_value)::int AS value_parcels,
          MODE() WITHIN GROUP (ORDER BY zoning_jurisdiction)
            FILTER (WHERE zoning_jurisdiction IS NOT NULL AND zoning_jurisdiction <> '')
            AS primary_zoning_jurisdiction
        FROM place_parcels
        GROUP BY county_fips, city_name
        HAVING COUNT(*) >= 1
        ORDER BY county_fips, parcel_count DESC, city_name
        """
    )
    rows = db.execute(sql).mappings().all()
    return [dict(r) for r in rows]


def zoning_path_for_city(
    *,
    county_fips: str,
    city_name: str,
    waza_parcels: int,
    zoned_parcels: int,
    parcel_count: int,
    primary_zoning_jurisdiction: str | None,
    phase_b: dict[str, str],
    catalog: dict[str, str],
    waza_counties: set[str],
) -> tuple[str, str, str]:
    """Return (zoning_source_kind, zoning_source_detail, zoning_url)."""
    cf = county_fips
    if cf == "24510":
        return (
            "baltimore_egis_overlay",
            "Baltimore City zoning districts + curated Article 32 YAML",
            "https://geodata.baltimorecity.gov/",
        )
    if cf == "53019":
        return (
            "none_no_traditional_zoning",
            "Ferry County FAQ — no traditional zoning districts; leave null",
            "",
        )

    waza_pct = (100.0 * waza_parcels / parcel_count) if parcel_count else 0.0
    zoned_pct = (100.0 * zoned_parcels / parcel_count) if parcel_count else 0.0
    juris = (primary_zoning_jurisdiction or "").strip()
    city_slug = _slug(city_name.replace("(unincorporated)", "unincorporated"))

    # Prefer explicit catalog city match, then Phase B county overlay, then WAZA.
    for key in (f"{city_slug}_city", city_slug, juris):
        if key and key in catalog:
            return ("city_gis_catalog", key, catalog[key])

    if cf in phase_b and zoned_pct >= 50:
        return (
            "county_phase_b_overlay",
            phase_b[cf],
            "",
        )

    if waza_pct >= 5 or waza_parcels >= 50 or cf in waza_counties:
        detail = juris or f"waza COUNTYFP filter + Jurisdiction for {city_name}"
        if waza_parcels < 50 and cf in waza_counties:
            detail = f"waza configured for county — populate/join remaining ({city_name})"
        return (
            "waza_statewide",
            detail,
            "https://services6.arcgis.com/tboeqGwETr5ppr5Q/arcgis/rest/services/WAZA_Prototype_Layers/FeatureServer/0",
        )

    if zoned_pct >= 20:
        return ("county_or_local_overlay_present", "zoning_code already on parcels", "")

    return (
        "needs_overlay_or_waza",
        "parcel base present; queue Phase B / WAZA populate for this county",
        "",
    )


def vacancy_path(county_fips: str, value_parcels: int, parcel_count: int) -> str:
    if county_fips.startswith("24"):
        return "baltimore_assessor_raw_properties"
    if value_parcels >= max(1, int(parcel_count * 0.5)):
        return "watech_VALUE_BLDG_VALUE_LAND"
    return "watech_or_assessor_thin"


def main() -> int:
    phase_b = _load_phase_b_zoning_counties()
    waza_counties = _load_waza_counties()
    catalog = _catalog_urls()
    db = _session()
    try:
        cities = fetch_city_rows(db)
    finally:
        db.close()

    # Any county that already has meaningful WAZA joins is a WAZA path for its cities.
    for row in cities:
        if int(row.get("waza_parcels") or 0) >= 100:
            waza_counties.add(str(row["county_fips"]))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "state_fips",
        "county_fips",
        "city_name",
        "city_slug",
        "parcel_count",
        "lat",
        "lon",
        "parcel_source",
        "zoning_source_kind",
        "zoning_source_detail",
        "zoning_source_url",
        "vacancy_source",
        "demand_source",
        "waza_parcels",
        "zoned_parcels",
        "value_parcels",
        "primary_zoning_jurisdiction",
        "demand_generator_emitted",
    ]

    demand_gens: list[dict] = []
    csv_rows: list[dict] = []

    for row in cities:
        cf = str(row["county_fips"])
        city = str(row["city_name"])
        n = int(row["parcel_count"] or 0)
        lat = float(row["lat"]) if row["lat"] is not None else None
        lon = float(row["lon"]) if row["lon"] is not None else None
        waza_n = int(row["waza_parcels"] or 0)
        zoned_n = int(row["zoned_parcels"] or 0)
        value_n = int(row["value_parcels"] or 0)
        juris = row.get("primary_zoning_jurisdiction")
        state = cf[:2]
        parcel_source = (
            "baltimore_egis"
            if cf == "24510"
            else "watech_current_parcels"
        )
        z_kind, z_detail, z_url = zoning_path_for_city(
            county_fips=cf,
            city_name=city,
            waza_parcels=waza_n,
            zoned_parcels=zoned_n,
            parcel_count=n,
            primary_zoning_jurisdiction=str(juris) if juris else None,
            phase_b=phase_b,
            catalog=catalog,
            waza_counties=waza_counties,
        )
        vac = vacancy_path(cf, value_n, n)
        emit_demand = (
            lat is not None
            and lon is not None
            and n >= MIN_PARCELS_FOR_DEMAND
            and city != "(unincorporated)"  # county seats already cover rural; avoid centroid spam
        )
        # Still emit unincorporated demand at county level once via seats file; cities only here.
        if city == "(unincorporated)":
            emit_demand = False

        if emit_demand:
            label = f"{city} ({cf}) — auto city centroid"
            demand_gens.append({"name": label, "lat": round(lat, 5), "lon": round(lon, 5)})

        csv_rows.append(
            {
                "state_fips": state,
                "county_fips": cf,
                "city_name": city,
                "city_slug": _slug(city),
                "parcel_count": n,
                "lat": f"{lat:.6f}" if lat is not None else "",
                "lon": f"{lon:.6f}" if lon is not None else "",
                "parcel_source": parcel_source,
                "zoning_source_kind": z_kind,
                "zoning_source_detail": z_detail,
                "zoning_source_url": z_url,
                "vacancy_source": vac,
                "demand_source": "auto_city_centroid" if emit_demand else "county_seat_or_metro_yaml",
                "waza_parcels": waza_n,
                "zoned_parcels": zoned_n,
                "value_parcels": value_n,
                "primary_zoning_jurisdiction": juris or "",
                "demand_generator_emitted": "yes" if emit_demand else "no",
            }
        )

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(csv_rows)

    header = (
        "# AUTO-GENERATED by scripts/build_city_prospect_registry.py — do not edit by hand.\n"
        "# Demand generators: one centroid per incorporated place (>= "
        f"{MIN_PARCELS_FOR_DEMAND} parcels).\n"
        "# Re-run after new county ingest or place backfill.\n"
    )
    OUT_DEMAND.write_text(
        header + yaml.safe_dump(demand_gens, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )

    kinds: dict[str, int] = {}
    for r in csv_rows:
        kinds[r["zoning_source_kind"]] = kinds.get(r["zoning_source_kind"], 0) + 1

    print(
        json.dumps(
            {
                "cities": len(csv_rows),
                "demand_generators": len(demand_gens),
                "csv": str(OUT_CSV),
                "demand_yaml": str(OUT_DEMAND),
                "zoning_source_kinds": kinds,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
