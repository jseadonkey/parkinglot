#!/usr/bin/env python3
"""Sync Washington incorporated-place agents from Census TIGERweb.

Outputs:
  - data/boundaries/wa/manifest/wa_incorporated_places.json
  - data/boundaries/wa/by_geoid/{GEOID}.geojson
  - config/generated/wa_city_geography_agents.yaml
  - data/zoning/wa/wa_city_surface_parking_rules_skeleton.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from shapely.geometry import shape

_REPO_ROOT = Path(__file__).resolve().parents[1]

PLACES_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/"
    "TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/4/query"
)
COUNTIES_URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
STATE_FIPS_WA = "53"


def _ensure_repo_paths() -> None:
    p = _REPO_ROOT / "packages/core"
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _query_geojson(url: str, where: str, *, return_geometry: bool = True) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "where": where,
            "outFields": "*",
            "returnGeometry": "true" if return_geometry else "false",
            "outSR": "4326",
            "f": "geojson",
        },
        quote_via=urllib.parse.quote,
    )
    with urllib.request.urlopen(f"{url}?{query}", timeout=90) as response:
        data = json.load(response)
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        msg = f"Unexpected GeoJSON response from {url}"
        raise TypeError(msg)
    return data


def _feature_properties(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") or {}
    return props if isinstance(props, dict) else {}


def _normalize_place_feature(feature: dict[str, Any]) -> dict[str, Any]:
    props = _feature_properties(feature)
    geoid = str(props.get("GEOID") or "").strip()
    if not geoid:
        msg = f"Place feature missing GEOID: {props}"
        raise ValueError(msg)
    basename = str(props.get("BASENAME") or props.get("NAME") or geoid).strip()
    return {
        "geoid": geoid,
        "name": str(props.get("NAME") or basename).strip(),
        "basename": basename,
        "state_fips": str(props.get("STATE") or STATE_FIPS_WA).strip(),
        "place_fips": str(props.get("PLACE") or geoid[-5:]).strip(),
        "lsadc": str(props.get("LSADC") or "").strip(),
        "funcstat": str(props.get("FUNCSTAT") or "").strip(),
        "feature": feature,
    }


def _county_fips_for_place(place_geom: Any, county_features: list[dict[str, Any]]) -> list[str]:
    counties: list[str] = []
    for county_feature in county_features:
        props = _feature_properties(county_feature)
        county_geoid = str(props.get("GEOID") or "").strip()
        if not county_geoid:
            continue
        county_geom = shape(county_feature["geometry"])
        if not county_geom.is_valid:
            county_geom = county_geom.buffer(0)
        if county_geom.is_empty or not county_geom.intersects(place_geom):
            continue
        intersection = county_geom.intersection(place_geom)
        if not intersection.is_empty and intersection.area > 0:
            counties.append(county_geoid)
    if counties:
        return sorted(set(counties))

    point = place_geom.representative_point()
    for county_feature in county_features:
        props = _feature_properties(county_feature)
        county_geoid = str(props.get("GEOID") or "").strip()
        if county_geoid and shape(county_feature["geometry"]).covers(point):
            return [county_geoid]
    return []


def _write_json(path: Path, payload: dict[str, Any], *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(payload, separators=(",", ":"), sort_keys=False)
    else:
        text = json.dumps(payload, indent=2, sort_keys=False)
    path.write_text(text + "\n", encoding="utf-8")


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, width=120), encoding="utf-8")


def _agent_key(geoid: str, slug: str, county_fips: str, multi_county: bool) -> str:
    base = f"wa_{geoid}_{slug}"
    return f"{base}_{county_fips}" if multi_county else base


def sync(expected_count: int) -> dict[str, Any]:
    _ensure_repo_paths()
    from parking_core.city_inventory import disambiguate_slugs

    places = _query_geojson(
        PLACES_URL,
        f"STATE='{STATE_FIPS_WA}' AND FUNCSTAT='A'",
        return_geometry=True,
    )
    counties = _query_geojson(COUNTIES_URL, f"STATE='{STATE_FIPS_WA}'", return_geometry=True)

    place_features = [_normalize_place_feature(feature) for feature in places.get("features") or []]
    if len(place_features) != expected_count:
        msg = f"Expected {expected_count} WA incorporated places, got {len(place_features)}"
        raise RuntimeError(msg)

    slug_by_geoid = disambiguate_slugs(place_features)
    lsadc_counts = Counter(str(place["lsadc"]) for place in place_features)
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    manifest_entries: list[dict[str, Any]] = []
    city_agents: list[dict[str, Any]] = []
    jurisdiction_keys: set[str] = set()
    county_slice_count = 0

    for place in sorted(place_features, key=lambda item: (item["basename"], item["geoid"])):
        geoid = place["geoid"]
        slug = slug_by_geoid[geoid]
        jurisdiction_key = f"{slug}_city"
        jurisdiction_keys.add(jurisdiction_key)
        feature = place["feature"]
        geom = shape(feature["geometry"])
        if not geom.is_valid:
            geom = geom.buffer(0)
        county_fips = _county_fips_for_place(geom, counties.get("features") or [])
        if not county_fips:
            msg = f"Could not assign counties for {place['name']} ({geoid})"
            raise RuntimeError(msg)
        boundary_path = f"data/boundaries/wa/by_geoid/{geoid}.geojson"
        out_feature = {
            "type": "Feature",
            "geometry": feature["geometry"],
            "properties": {
                **_feature_properties(feature),
                "slug": slug,
                "jurisdiction_key": jurisdiction_key,
                "county_fips": county_fips,
            },
        }
        _write_json(
            _REPO_ROOT / boundary_path,
            {"type": "FeatureCollection", "features": [out_feature]},
            compact=True,
        )
        manifest_entries.append(
            {
                "geoid": geoid,
                "name": place["name"],
                "basename": place["basename"],
                "slug": slug,
                "state_fips": place["state_fips"],
                "place_fips": place["place_fips"],
                "lsadc": place["lsadc"],
                "funcstat": place["funcstat"],
                "jurisdiction_key": jurisdiction_key,
                "boundary_path": boundary_path,
                "county_fips": county_fips,
            }
        )

        multi_county = len(county_fips) > 1
        for county in county_fips:
            county_slice_count += 1
            city_agents.append(
                {
                    "key": _agent_key(geoid, slug, county, multi_county),
                    "name": f"{place['name']} ({county})" if multi_county else place["name"],
                    "type": "city",
                    "state_fips": STATE_FIPS_WA,
                    "county_fips": county,
                    "jurisdiction_key": jurisdiction_key,
                    "boundary_path": boundary_path,
                    "source_refs": [
                        "watech_statewide_parcels",
                        "census_tiger_incorporated_places_wa",
                        "wa_city_zoning_inventory_template",
                        "wa_city_rules_skeleton",
                    ],
                    "zoning_rules_paths": ["data/zoning/wa/wa_city_surface_parking_rules_skeleton.yaml"],
                    "notes": (
                        "Generated from Census TIGERweb incorporated places; "
                        "zoning entries are conservative until curated."
                    ),
                }
            )

    manifest = {
        "source_url": PLACES_URL,
        "state_fips": STATE_FIPS_WA,
        "generated_at": generated_at,
        "place_count": len(manifest_entries),
        "county_slice_count": county_slice_count,
        "lsadc_counts": dict(sorted(lsadc_counts.items())),
        "entries": manifest_entries,
    }
    _write_json(_REPO_ROOT / "data/boundaries/wa/manifest/wa_incorporated_places.json", manifest)
    _write_yaml(
        _REPO_ROOT / "config/generated/wa_city_geography_agents.yaml",
        {
            "generated_at": generated_at,
            "source_url": PLACES_URL,
            "geographies": city_agents,
        },
    )
    _write_yaml(
        _REPO_ROOT / "data/zoning/wa/wa_city_surface_parking_rules_skeleton.yaml",
        {
            "version": 1,
            "default_when_unknown": False,
            "jurisdictions": {
                jurisdiction_key: {
                    "source_url": "config/geography_registry.yaml",
                    "zones": {},
                }
                for jurisdiction_key in sorted(jurisdiction_keys)
            },
        },
    )

    return {
        "place_count": len(manifest_entries),
        "county_slice_count": county_slice_count,
        "lsadc_counts": dict(sorted(lsadc_counts.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync WA incorporated city/town agents from Census TIGERweb.")
    parser.add_argument("--expected-count", type=int, default=281)
    parser.add_argument("--json", action="store_true", help="Print machine-readable summary")
    args = parser.parse_args()

    summary = sync(args.expected_count)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"WA incorporated places: {summary['place_count']}")
        print(f"WA city/county slices: {summary['county_slice_count']}")
        print(f"LSADC counts: {summary['lsadc_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
