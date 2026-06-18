# Zoning sources - Asotin County, WA

**Disclaimer:** Operational GIS guidance only. This is not legal advice and not a substitute for title, survey, or counsel review.

## Jurisdiction split

Parcels in **Asotin County (`53003`)** must be assigned to the zoning authority that controls the parcel:

- **`asotin_unincorporated`** for unincorporated county zoning.
- Seeded city jurisdictions below for parcels inside incorporated city limits.

Do not apply county zoning to city parcels or city zoning to unincorporated parcels. The overlay must emit `ZONING_JURISDICTION` explicitly.

## Countywide parcel and assessor source

| Purpose | Source | URL | Join / useful fields | Status |
|---------|--------|-----|----------------------|--------|
| Statewide parcel ingest | WaTech Washington State Parcels | https://geo.wa.gov/datasets/watech::washington-state-parcels-parcels-current/about | `FIPS_NR`, `PARCEL_ID_NR`, `APN`, situs aliases | baseline |
| County assessor/value/address enrichment | Asotin County assessor roll | TBD - official county assessor/parcel roll | APN;PARCEL_ID_NR;PIN; situs: TBD; mailing: TBD | not_started |

## Unincorporated county zoning source

| Jurisdiction | Source | URL | Zone fields | Status |
|--------------|--------|-----|-------------|--------|
| `asotin_unincorporated` | Asotin County unincorporated zoning | TBD - official county zoning GIS/service | TBD | not_started |

Ordinance/use-table references to curate before trusting scores:

- Asotin County zoning/use table - TODO


## Seeded city zoning sources

| Jurisdiction | City | Source URL | Ordinance/use table | Notes |
|--------------|------|------------|---------------------|-------|
| (none seeded yet) | Add city id to `wa_cities_seed.yaml` when city candidates justify tracking. | TBD | TBD | TBD |

## Workflow into this repository

1. Download or query the county and city zoning polygon layers.
2. Split parcels by city boundary / unincorporated area before assigning zoning.
3. Spatially join parcel centroid or parcel polygon to the controlling jurisdiction layer.
4. Emit an overlay GeoJSON with:
   - `COUNTY_FIPS`: `53003`
   - `ZONING`: normalized local zone code
   - `ZONING_JURISDICTION`: one of the jurisdiction keys above
   - optional `ZONING_ALLOWS_SURFACE_PARKING`: only when ordinance/legal review explicitly approves it
5. Update `data/zoning/wa/wa_county_surface_parking_rules.yaml` with curated zone mappings.
6. Move governance status from `not_started` only after source, use table, and sample parcel QA pass.

## Current scoring stance

The generated rules file keeps `default_when_unknown: false` and leaves this county's `zones` empty until curation. Unknown codes get no by-right surface-parking credit.

## Related files

- `docs/zoning-sources-asotin.md`
- `data/zoning/wa/wa_county_surface_parking_rules.yaml`
- `data/zoning/governance.yaml`
- `data/jurisdictions/wa/source_catalog.csv`
- `data/jurisdictions/wa/address_source_chains.yaml`
- `data/jurisdictions/wa/address_field_maps.yaml`
