# Geography agents and jurisdiction resolution

This repo now has a structured geography-agent registry at
`config/geography_registry.yaml`.

In this codebase, a "geography agent" is a deterministic configuration record,
not an LLM persona. It binds a city, county, or county-unincorporated area to:

- authoritative source inventory entries,
- a zoning jurisdiction key,
- optional municipal boundary GeoJSON,
- zoning rules files,
- the standard scoring profiles (`identification`, `entitlement`, `strategic`),
- data-quality checks.

## What this corrects

| Previous gap | Current implementation |
| --- | --- |
| No agent/registry for every city | The registry includes state-level Census/TIGER incorporated-place inventory sources for WA and MD. City records can be added or generated from those authoritative sources; Kent is the first registered city with a boundary file. |
| No county/unincorporated coverage for all counties | Every county in `config/pilot.yaml` now has a default county/consolidated or county-unincorporated geography agent. |
| No automatic jurisdiction resolver | `parking_ingestion.jurisdiction_resolver` resolves explicit `ZONING_JURISDICTION`, then registered city boundaries, then county/unincorporated defaults. |
| No per-jurisdiction favorability database | All registered jurisdiction keys have conservative false-by-default zoning-rules blocks; Baltimore City has curated positive/negative entries, while other skeletons remain safe until ordinance-backed entries are added. |
| No source-of-truth inventory | `config/geography_registry.yaml` has structured `sources` records with source type, URL/path, cadence, coverage, and notes. |
| No geography-specific data quality | `scripts/validate_geography_registry.py` and `scripts/validate_phase_b_overlay.py` report registry/source/rules coverage and overlay jurisdiction resolution. |

## Resolution order

For each parcel:

1. If the source GeoJSON has `ZONING_JURISDICTION`, use it.
2. Else, if the county has registered city boundaries, test the parcel geometry
   against those boundaries.
3. Else, fall back to the county's default county/unincorporated jurisdiction.

The GeoJSON loader persists the resolved value into both `attrs["zoning_jurisdiction"]`
and `raw_properties["ZONING_JURISDICTION"]` so downstream scoring, validation, and
exports can inspect the same jurisdiction key.

## Validation commands

```bash
python3 scripts/validate_geography_registry.py
python3 scripts/validate_phase_b_overlay.py /path/to/overlay.geojson
```

The registry validator exits non-zero only on structural errors. Empty zoning-rule
blocks are reported as informational because they are deliberately conservative:
unknown zoning does not receive surface-parking credit.

## Adding a city

1. Add or refresh a boundary GeoJSON under `data/boundaries/<state>/`.
2. Add a `city` entry in `config/geography_registry.yaml` with:
   - `county_fips`,
   - `jurisdiction_key`,
   - `boundary_path`,
   - source refs for parcel, boundary, zoning, and rules.
3. Add or update a rules block under `data/zoning/...`.
4. Run `python3 scripts/validate_geography_registry.py`.
5. Re-run Phase B overlay validation/merge for parcels in that county.

## Safety stance

For jurisdictions without curated ordinance entries, zoning stays conservative:
`default_when_unknown: false`. Those parcels can still ingest and score, but they
do not get favorable-zoning credit until the local zone codes are backed by a
source memo and rules entry.
