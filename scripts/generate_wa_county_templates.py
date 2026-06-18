#!/usr/bin/env python3
"""Generate WA county source, address, governance, and zoning-rule templates."""

from __future__ import annotations

import ast
import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
PILOT_SCOPE = REPO / "services" / "api" / "app" / "pilot_scope.py"
CITIES_SEED = REPO / "data" / "jurisdictions" / "wa" / "wa_cities_seed.yaml"
CATALOG = REPO / "data" / "jurisdictions" / "wa" / "source_catalog.csv"
ADDRESS_CHAINS = REPO / "data" / "jurisdictions" / "wa" / "address_source_chains.yaml"
ADDRESS_MAPS = REPO / "data" / "jurisdictions" / "wa" / "address_field_maps.yaml"
RULES = REPO / "data" / "zoning" / "wa" / "wa_county_surface_parking_rules.yaml"
GOVERNANCE = REPO / "data" / "zoning" / "governance.yaml"
DOCS = REPO / "docs"

CATALOG_FIELDS = [
    "source_id",
    "source_type",
    "jurisdiction_id",
    "county_fips",
    "source_name",
    "source_url",
    "api_type",
    "address_situs_fields",
    "address_mailing_fields",
    "join_key",
    "license_notes",
    "refresh_frequency_target",
    "address_source_status",
    "last_checked_at",
    "provenance_notes",
]


@dataclass(frozen=True)
class SourceDetails:
    county_zoning_url: str = ""
    county_zoning_api_type: str = "tbd"
    county_zoning_fields: str = "TBD"
    county_zoning_status: str = "not_started"
    county_zoning_notes: str = "Template row; identify official county unincorporated zoning GIS/service."
    assessor_url: str = ""
    assessor_api_type: str = "tbd"
    assessor_situs_fields: str = "TBD"
    assessor_mailing_fields: str = "TBD"
    assessor_join_key: str = "APN;PARCEL_ID_NR;PIN"
    assessor_status: str = "not_started"
    assessor_notes: str = "Template row; identify official county assessor roll or parcel service."
    ordinance_refs: tuple[str, ...] = ()


KNOWN_COUNTY_SOURCES: dict[str, SourceDetails] = {
    "53033": SourceDetails(
        county_zoning_url="https://gis-kingcounty.opendata.arcgis.com/datasets/kingcounty::zoning-for-unincorporated-king-county",
        county_zoning_api_type="arcgis_feature_server",
        county_zoning_fields="CURRZONE;ZONING;ZONE",
        county_zoning_status="source_found",
        county_zoning_notes="Unincorporated King County zoning; city parcels require city zoning layers.",
        assessor_url="https://gismaps.kingcounty.gov/parcelviewer2/",
        assessor_api_type="arcgis_feature_server",
        assessor_join_key="PIN",
        assessor_status="source_found",
        assessor_notes="Existing King County assessor-roll merge placeholder.",
        ordinance_refs=("King County Title 21A use tables",),
    ),
    "53077": SourceDetails(
        county_zoning_url="https://maps.yakimacounty.us/server/rest/services/Planning/CountyZoning/MapServer/0",
        county_zoning_api_type="arcgis_mapserver",
        county_zoning_fields="ZONE;JURISDICT;STATUS;Description",
        county_zoning_status="source_found",
        county_zoning_notes="Official Yakima County CountyZoning layer; layer is for unincorporated county zoning, not City of Yakima.",
        assessor_url="https://maps.yakimacounty.us/server/rest/services/Assessor/Taxlots/FeatureServer",
        assessor_api_type="arcgis_feature_server",
        assessor_situs_fields="SITUS_ADDR;SITUS_CITY;SITUS_ZIP",
        assessor_mailing_fields="MAILING_AD;MAILING_CI;MAILING_STATE;MAILING_ZIP",
        assessor_join_key="ASSESSOR_N;TAXLOT_N",
        assessor_status="source_found",
        assessor_notes="Taxlots layer 2 and Property table 10 include situs/value aliases; connector still pending.",
        ordinance_refs=(
            "Yakima County Code Ch. 19.14 Allowable Land Use Table",
            "Yakima County Code Ch. 19.22 Parking and Loading",
        ),
    ),
}

KNOWN_CITY_ZONING_URLS: dict[str, tuple[str, str, str]] = {
    "kent_city": (
        "https://gis-cityofkent.opendata.arcgis.com/datasets/kent-zoning-districts",
        "arcgis_feature_server",
        "Kent zoning districts; see docs/zoning-sources-kent.md.",
    ),
    "yakima_city": (
        "https://gis.yakimawa.gov/citymap/",
        "web_map",
        "CityMap is the official City of Yakima parcel/zoning lookup; export/API path requires follow-up.",
    ),
}

CITY_ORDINANCE_REFS: dict[str, tuple[str, ...]] = {
    "yakima_city": (
        "Yakima Municipal Code Title 15 Table 4-1",
        "Yakima Municipal Code Ch. 15.06 Off-street Parking and Loading",
    ),
    "kent_city": ("Kent zoning code and parking/use table",),
}


def _wa_county_names() -> dict[str, str]:
    tree = ast.parse(PILOT_SCOPE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "WA_COUNTY_NAMES" and node.value is not None:
                value = ast.literal_eval(node.value)
                return dict(value) if isinstance(value, dict) else {}
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "WA_COUNTY_NAMES":
                    value = ast.literal_eval(node.value)
                    return dict(value) if isinstance(value, dict) else {}
    return {}


def _load_cities() -> dict[str, list[dict[str, str]]]:
    raw = yaml.safe_load(CITIES_SEED.read_text(encoding="utf-8"))
    block = raw.get("cities_by_county_fips") if isinstance(raw, dict) else {}
    return block if isinstance(block, dict) else {}


def _slug(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


def _doc_slug(name: str) -> str:
    return _slug(name).replace("_", "-")


def _county_id(name: str) -> str:
    return f"{_slug(name)}_county"


def _unincorporated_id(name: str) -> str:
    return f"{_slug(name)}_unincorporated"


def _read_catalog() -> list[dict[str, str]]:
    if not CATALOG.is_file():
        return []
    with CATALOG.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_catalog(rows: list[dict[str, str]]) -> None:
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    with CATALOG.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CATALOG_FIELDS)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in CATALOG_FIELDS} for row in rows])


def _merge_catalog_rows(new_rows: list[dict[str, str]]) -> None:
    existing = _read_catalog()
    by_id = {row.get("source_id", ""): row for row in existing if row.get("source_id")}
    for row in new_rows:
        sid = row["source_id"]
        if sid not in by_id:
            by_id[sid] = row
    ordered_existing = [row for row in existing if row.get("source_id") in by_id]
    existing_ids = {row.get("source_id") for row in ordered_existing}
    appended = [by_id[row["source_id"]] for row in new_rows if row["source_id"] not in existing_ids]
    _write_catalog(ordered_existing + appended)


def _catalog_rows(counties: dict[str, str], cities: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    today = datetime.now(UTC).date().isoformat()
    rows: list[dict[str, str]] = []
    for fips, name in sorted(counties.items()):
        details = KNOWN_COUNTY_SOURCES.get(fips, SourceDetails())
        county_slug = _slug(name)
        county_id = _county_id(name)
        uninc_id = _unincorporated_id(name)
        doc = f"docs/zoning-sources-{_doc_slug(name)}.md"
        rows.append(
            {
                "source_id": f"{county_slug}_unincorporated_zoning",
                "source_type": "zoning",
                "jurisdiction_id": uninc_id,
                "county_fips": fips,
                "source_name": f"{name} County unincorporated zoning",
                "source_url": details.county_zoning_url,
                "api_type": details.county_zoning_api_type,
                "address_situs_fields": "",
                "address_mailing_fields": "",
                "join_key": details.county_zoning_fields,
                "license_notes": "Verify county GIS/open-data terms before production redistribution.",
                "refresh_frequency_target": "monthly",
                "address_source_status": details.county_zoning_status,
                "last_checked_at": today,
                "provenance_notes": f"{details.county_zoning_notes} See {doc}.",
            }
        )
        rows.append(
            {
                "source_id": f"{county_slug}_assessor_roll",
                "source_type": "assessor_value",
                "jurisdiction_id": county_id,
                "county_fips": fips,
                "source_name": f"{name} County assessor roll",
                "source_url": details.assessor_url,
                "api_type": details.assessor_api_type,
                "address_situs_fields": details.assessor_situs_fields,
                "address_mailing_fields": details.assessor_mailing_fields,
                "join_key": details.assessor_join_key,
                "license_notes": "Verify county assessor/open-data terms before production use.",
                "refresh_frequency_target": "weekly",
                "address_source_status": details.assessor_status,
                "last_checked_at": today,
                "provenance_notes": details.assessor_notes,
            }
        )
        for city in cities.get(fips, []):
            city_id = str(city.get("id") or "").strip()
            city_name = str(city.get("name") or "").strip()
            if not city_id or not city_name:
                continue
            url, api_type, notes = KNOWN_CITY_ZONING_URLS.get(
                city_id,
                ("", "tbd", "Template row; identify official city zoning GIS/service."),
            )
            status = "source_found" if url else "not_started"
            rows.append(
                {
                    "source_id": f"{city_id}_zoning",
                    "source_type": "zoning",
                    "jurisdiction_id": city_id,
                    "county_fips": fips,
                    "source_name": f"{city_name} city zoning",
                    "source_url": url,
                    "api_type": api_type,
                    "address_situs_fields": "",
                    "address_mailing_fields": "",
                    "join_key": "ZONING;ZONE;DISTRICT;TBD",
                    "license_notes": "Verify city GIS/open-data terms before production redistribution.",
                    "refresh_frequency_target": "monthly",
                    "address_source_status": status,
                    "last_checked_at": today,
                    "provenance_notes": f"{notes} See {doc}.",
                }
            )
    return rows


def _write_address_chains(counties: dict[str, str]) -> None:
    chains: dict[str, Any] = {
        "baltimore_city": {
            "jurisdiction_id": "baltimore_city",
            "county_fips": "24510",
            "sources": ["baltimore_realproperty", "baltimore_address_points"],
        },
        "default_wa_county": {
            "jurisdiction_id": None,
            "county_fips": None,
            "sources": ["watech_statewide_parcels", "wa_county_assessor_roll", "nominatim_centroid_fallback"],
        },
    }
    overrides = {"24510": "baltimore_city"}
    for fips, name in sorted(counties.items()):
        cid = _county_id(name)
        assessor = f"{_slug(name)}_assessor_roll"
        chains[cid] = {
            "jurisdiction_id": cid,
            "county_fips": fips,
            "sources": ["watech_statewide_parcels", assessor, "nominatim_centroid_fallback"],
        }
        overrides[fips] = cid
    payload = {
        "version": 1,
        "chains": chains,
        "county_overrides": overrides,
    }
    ADDRESS_CHAINS.write_text(
        "# Ordered fallback chains per jurisdiction. Generated by scripts/generate_wa_county_templates.py.\n"
        "# The address-health agent advances when coverage remains below rollout thresholds.\n\n"
        + yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def _write_address_maps(counties: dict[str, str]) -> None:
    default_map: dict[str, Any] = {
        "address_source": "watech_statewide",
        "situs_street": [
            "SITUS_ADDRESS",
            "situs_address",
            "SITUS_ADDR",
            "situs_addr",
            "ADDR_FULL",
            "addr_full",
            "FULLADDR",
            "fulladdr",
            "PROPERTY_ADDRESS",
            "property_address",
            "LOC_STREET",
            "loc_street",
            "SITE_ADDR",
            "site_addr",
            "SUB_ADDRESS",
            "sub_address",
        ],
        "situs_city": ["SITUS_CITY_NM", "SITUS_CITY", "situs_city", "LOC_CITY", "loc_city", "CITY", "city"],
        "situs_state": ["SITUS_STATE", "situs_state", "STATE", "state"],
        "situs_zip": ["SITUS_ZIP_NR", "SITUS_ZIP", "situs_zip", "ZIP5", "zip", "POSTAL_CODE"],
        "mailing": ["MAILING_ADDRESS", "mailing_address", "MAIL_ADDR", "mail_addr", "MAILTOADD", "mailtoadd", "FULL_MAILING", "full_mailing"],
        "owner": ["OWNER_NAME", "owner_name", "TAXPAYER_NAME", "taxpayer_name"],
    }
    county_maps: dict[str, Any] = {}
    for fips, name in sorted(counties.items()):
        county_maps[fips] = {
            "inherit": "default_wa_watech",
            "address_source": f"watech_{_slug(name)}",
            "notes": f"{name} County - WaTech statewide layer first; county assessor roll merge is templated in source_catalog.",
        }
    county_maps["53077"].update(
        {
            "notes": (
                "Yakima County - WaTech statewide first; county Taxlots FeatureServer aliases include "
                "SITUS_ADDR/SITUS_CITY/SITUS_ZIP and ASSESSOR_N/TAXLOT_N."
            ),
            "assessor_situs_street": ["SITUS_ADDR", "LOCATED_ON"],
            "assessor_situs_city": ["SITUS_CITY"],
            "assessor_situs_zip": ["SITUS_ZIP"],
            "assessor_mailing": ["MAILING_AD", "MAILING_CI", "MAILING_STATE", "MAILING_ZIP"],
            "assessor_owner": ["ORG_NAME", "FIRST_NAME", "LAST_NAME"],
        }
    )
    payload = {
        "default_wa_watech": default_map,
        "counties": county_maps,
        "non_wa": {
            "24510": {
                "address_source": "baltimore_realproperty",
                "notes": "Baltimore City - normalized in baltimore_parcels.py / address backfill batch.",
            }
        },
    }
    ADDRESS_MAPS.write_text(
        "# County/city situs + mailing field maps for ingest normalization.\n"
        "# Generated by scripts/generate_wa_county_templates.py.\n\n"
        + yaml.safe_dump(payload, sort_keys=False, width=120),
        encoding="utf-8",
    )


def _rules_block(counties: dict[str, str], cities: dict[str, list[dict[str, str]]]) -> str:
    lines = [
        "# Washington county/city surface-parking zoning templates.",
        "# Generated by scripts/generate_wa_county_templates.py.",
        "# Unknown and uncurated zone codes must remain conservative.",
        "",
        "version: 1",
        "default_when_unknown: false",
        "",
        "jurisdictions:",
    ]
    for fips, name in sorted(counties.items()):
        doc = f"docs/zoning-sources-{_doc_slug(name)}.md"
        details = KNOWN_COUNTY_SOURCES.get(fips, SourceDetails())
        ordinance = "; ".join(details.ordinance_refs) if details.ordinance_refs else f"{name} County zoning/use table - TODO"
        lines.extend(
            [
                f"  {_unincorporated_id(name)}:",
                f"    source_doc: \"{doc}\"",
                f"    source_url: \"{details.county_zoning_url}\"",
                f"    ordinance_ref: \"{ordinance}\"",
                "    note: \"Template only; do not score as by-right until ordinance use table is curated.\"",
                "    zones: {}",
            ]
        )
        for city in cities.get(fips, []):
            city_id = str(city.get("id") or "").strip()
            city_name = str(city.get("name") or "").strip()
            if not city_id or not city_name:
                continue
            url, _api_type, _notes = KNOWN_CITY_ZONING_URLS.get(city_id, ("", "tbd", ""))
            refs = CITY_ORDINANCE_REFS.get(city_id, (f"{city_name} zoning/use table - TODO",))
            lines.extend(
                [
                    f"  {city_id}:",
                    f"    source_doc: \"{doc}\"",
                    f"    source_url: \"{url}\"",
                    f"    ordinance_ref: \"{'; '.join(refs)}\"",
                    "    note: \"Template only; city zoning controls inside city limits.\"",
                    "    zones: {}",
                ]
            )
    return "\n".join(lines) + "\n"


def _write_rules(counties: dict[str, str], cities: dict[str, list[dict[str, str]]]) -> None:
    RULES.write_text(_rules_block(counties, cities), encoding="utf-8")


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return raw if isinstance(raw, dict) else {}


def _write_governance(counties: dict[str, str], cities: dict[str, list[dict[str, str]]]) -> None:
    gov = _load_yaml(GOVERNANCE)
    gov.setdefault("version", 1)
    gov.setdefault(
        "policy",
        {
            "full_credit_symbols": ["P"],
            "conditional_symbols": ["CB"],
            "council_symbols": ["CO"],
            "unknown_default_must_be_false": True,
        },
    )
    coverage = gov.setdefault("county_coverage", {})
    jurisdictions = gov.setdefault("jurisdictions", {})
    for fips, name in sorted(counties.items()):
        jkeys = [_unincorporated_id(name)]
        jkeys.extend(str(city.get("id") or "").strip() for city in cities.get(fips, []) if str(city.get("id") or "").strip())
        coverage[fips] = {
            "county_name": f"{name} County, WA",
            "status": "not_started",
            "jurisdiction_keys": jkeys,
            "note": "Template coverage is ready; zoning score remains untrusted until each listed jurisdiction is curated.",
        }
        details = KNOWN_COUNTY_SOURCES.get(fips, SourceDetails())
        jurisdictions.setdefault(
            _unincorporated_id(name),
            {
                "display_name": f"Unincorporated {name} County, WA",
                "status": "not_started",
                "state_fips": "53",
                "county_fips": [fips],
                "authority": f"{name} County zoning code",
                "rules_file": "data/zoning/wa/wa_county_surface_parking_rules.yaml",
                "source_doc": f"docs/zoning-sources-{_doc_slug(name)}.md",
                "legal_review_required": True,
                "scoring_policy": "Do not trust zoning score until county ordinance use table is curated.",
                "last_reviewed": None,
                "reviewed_by": None,
            },
        )
        if details.county_zoning_status == "source_found":
            jurisdictions[_unincorporated_id(name)]["source_url"] = details.county_zoning_url
        for city in cities.get(fips, []):
            city_id = str(city.get("id") or "").strip()
            city_name = str(city.get("name") or "").strip()
            if not city_id or not city_name:
                continue
            jurisdictions.setdefault(
                city_id,
                {
                    "display_name": f"{city_name}, WA",
                    "status": "not_started",
                    "state_fips": "53",
                    "county_fips": [fips],
                    "authority": f"{city_name} zoning code",
                    "rules_file": "data/zoning/wa/wa_county_surface_parking_rules.yaml",
                    "source_doc": f"docs/zoning-sources-{_doc_slug(name)}.md",
                    "legal_review_required": True,
                    "scoring_policy": "Do not trust zoning score until city ordinance use table is curated.",
                    "last_reviewed": None,
                    "reviewed_by": None,
                },
            )
    GOVERNANCE.write_text(yaml.safe_dump(gov, sort_keys=False, width=120), encoding="utf-8")


def _doc_for_county(fips: str, name: str, city_rows: list[dict[str, str]]) -> str:
    details = KNOWN_COUNTY_SOURCES.get(fips, SourceDetails())
    doc = f"docs/zoning-sources-{_doc_slug(name)}.md"
    zoning_url = details.county_zoning_url or "TBD - official county zoning GIS/service"
    assessor_url = details.assessor_url or "TBD - official county assessor/parcel roll"
    ordinance_refs = details.ordinance_refs or (f"{name} County zoning/use table - TODO",)
    ordinance_lines = "".join(f"- {ref}\n" for ref in ordinance_refs)
    city_lines = []
    if city_rows:
        for city in city_rows:
            city_id = str(city.get("id") or "").strip()
            city_name = str(city.get("name") or "").strip()
            url, _api_type, notes = KNOWN_CITY_ZONING_URLS.get(
                city_id,
                ("TBD - official city zoning GIS/service", "tbd", "Identify city GIS and ordinance use table."),
            )
            refs = CITY_ORDINANCE_REFS.get(city_id, (f"{city_name} zoning/use table - TODO",))
            city_lines.append(f"| `{city_id}` | {city_name} | {url} | {'; '.join(refs)} | {notes} |")
    else:
        city_lines.append("| (none seeded yet) | Add city id to `wa_cities_seed.yaml` when city candidates justify tracking. | TBD | TBD | TBD |")

    return f"""# Zoning sources - {name} County, WA

**Disclaimer:** Operational GIS guidance only. This is not legal advice and not a substitute for title, survey, or counsel review.

## Jurisdiction split

Parcels in **{name} County (`{fips}`)** must be assigned to the zoning authority that controls the parcel:

- **`{_unincorporated_id(name)}`** for unincorporated county zoning.
- Seeded city jurisdictions below for parcels inside incorporated city limits.

Do not apply county zoning to city parcels or city zoning to unincorporated parcels. The overlay must emit `ZONING_JURISDICTION` explicitly.

## Countywide parcel and assessor source

| Purpose | Source | URL | Join / useful fields | Status |
|---------|--------|-----|----------------------|--------|
| Statewide parcel ingest | WaTech Washington State Parcels | https://geo.wa.gov/datasets/watech::washington-state-parcels-parcels-current/about | `FIPS_NR`, `PARCEL_ID_NR`, `APN`, situs aliases | baseline |
| County assessor/value/address enrichment | {name} County assessor roll | {assessor_url} | {details.assessor_join_key}; situs: {details.assessor_situs_fields}; mailing: {details.assessor_mailing_fields} | {details.assessor_status} |

## Unincorporated county zoning source

| Jurisdiction | Source | URL | Zone fields | Status |
|--------------|--------|-----|-------------|--------|
| `{_unincorporated_id(name)}` | {name} County unincorporated zoning | {zoning_url} | {details.county_zoning_fields} | {details.county_zoning_status} |

Ordinance/use-table references to curate before trusting scores:

{ordinance_lines}

## Seeded city zoning sources

| Jurisdiction | City | Source URL | Ordinance/use table | Notes |
|--------------|------|------------|---------------------|-------|
{chr(10).join(city_lines)}

## Workflow into this repository

1. Download or query the county and city zoning polygon layers.
2. Split parcels by city boundary / unincorporated area before assigning zoning.
3. Spatially join parcel centroid or parcel polygon to the controlling jurisdiction layer.
4. Emit an overlay GeoJSON with:
   - `COUNTY_FIPS`: `{fips}`
   - `ZONING`: normalized local zone code
   - `ZONING_JURISDICTION`: one of the jurisdiction keys above
   - optional `ZONING_ALLOWS_SURFACE_PARKING`: only when ordinance/legal review explicitly approves it
5. Update `data/zoning/wa/wa_county_surface_parking_rules.yaml` with curated zone mappings.
6. Move governance status from `not_started` only after source, use table, and sample parcel QA pass.

## Current scoring stance

The generated rules file keeps `default_when_unknown: false` and leaves this county's `zones` empty until curation. Unknown codes get no by-right surface-parking credit.

## Related files

- `{doc}`
- `data/zoning/wa/wa_county_surface_parking_rules.yaml`
- `data/zoning/governance.yaml`
- `data/jurisdictions/wa/source_catalog.csv`
- `data/jurisdictions/wa/address_source_chains.yaml`
- `data/jurisdictions/wa/address_field_maps.yaml`
"""


def _write_docs(counties: dict[str, str], cities: dict[str, list[dict[str, str]]]) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    for fips, name in sorted(counties.items()):
        path = DOCS / f"zoning-sources-{_doc_slug(name)}.md"
        path.write_text(_doc_for_county(fips, name, cities.get(fips, [])), encoding="utf-8")


def main() -> int:
    counties = _wa_county_names()
    cities = _load_cities()
    if not counties:
        raise RuntimeError("No WA counties found in pilot_scope.py")
    _merge_catalog_rows(_catalog_rows(counties, cities))
    _write_address_chains(counties)
    _write_address_maps(counties)
    _write_rules(counties, cities)
    _write_governance(counties, cities)
    _write_docs(counties, cities)
    print(f"Generated WA templates for {len(counties)} counties and {sum(len(v) for v in cities.values())} seeded cities.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
