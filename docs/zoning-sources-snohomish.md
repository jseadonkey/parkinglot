# Zoning sources - Snohomish County, WA

**Disclaimer:** Operational GIS guidance only. This is not legal advice and not a substitute for title, survey, or counsel review.

## Jurisdiction split

Parcels in **Snohomish County (`53061`)** must be assigned to the zoning authority that controls the parcel:

- **`snohomish_unincorporated`** for unincorporated county zoning.
- Seeded city jurisdictions below for parcels inside incorporated city limits.

Do not apply county zoning to city parcels or city zoning to unincorporated parcels. The overlay must emit `ZONING_JURISDICTION` explicitly.

## Countywide parcel and assessor source

| Purpose | Source | URL | Join / useful fields | Status |
|---------|--------|-----|----------------------|--------|
| Statewide parcel ingest | WaTech Washington State Parcels | https://geo.wa.gov/datasets/watech::washington-state-parcels-parcels-current/about | `FIPS_NR`, `PARCEL_ID_NR`, `APN`, situs aliases | baseline |
| County assessor/value/address enrichment | Snohomish County assessor roll | TBD - official county assessor/parcel roll | APN;PARCEL_ID_NR;PIN; situs: TBD; mailing: TBD | not_started |

## Unincorporated county zoning source

| Jurisdiction | Source | URL | Zone fields | Status |
|--------------|--------|-----|-------------|--------|
| `snohomish_unincorporated` | Snohomish County unincorporated zoning | TBD - official county zoning GIS/service | TBD | not_started |

Ordinance/use-table references to curate before trusting scores:

- Snohomish County zoning/use table - TODO


## Seeded city zoning sources

| Jurisdiction | City | Source URL | Ordinance/use table | Notes |
|--------------|------|------------|---------------------|-------|
| `everett_city` | Everett | TBD - official city zoning GIS/service | Everett zoning/use table - TODO | Identify city GIS and ordinance use table. |
| `lynnwood_city` | Lynnwood | TBD - official city zoning GIS/service | Lynnwood zoning/use table - TODO | Identify city GIS and ordinance use table. |
| `edmonds_city` | Edmonds | TBD - official city zoning GIS/service | Edmonds zoning/use table - TODO | Identify city GIS and ordinance use table. |

## Workflow into this repository

1. Download or query the county and city zoning polygon layers.
2. Split parcels by city boundary / unincorporated area before assigning zoning.
3. Spatially join parcel centroid or parcel polygon to the controlling jurisdiction layer.
4. Emit an overlay GeoJSON with:
   - `COUNTY_FIPS`: `53061`
   - `ZONING`: normalized local zone code
   - `ZONING_JURISDICTION`: one of the jurisdiction keys above
   - optional `ZONING_ALLOWS_SURFACE_PARKING`: only when ordinance/legal review explicitly approves it
5. Update `data/zoning/wa/wa_county_surface_parking_rules.yaml` with curated zone mappings.
6. Move governance status from `not_started` only after source, use table, and sample parcel QA pass.

## Current scoring stance

The generated rules file keeps `default_when_unknown: false` and leaves this county's `zones` empty until curation. Unknown codes get no by-right surface-parking credit.

## Related files

- `docs/zoning-sources-snohomish.md`
- `data/zoning/wa/wa_county_surface_parking_rules.yaml`
- `data/zoning/governance.yaml`
- `data/jurisdictions/wa/source_catalog.csv`
- `data/jurisdictions/wa/address_source_chains.yaml`
- `data/jurisdictions/wa/address_field_maps.yaml`
