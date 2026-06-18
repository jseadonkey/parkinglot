# Zoning sources - King County, WA

**Disclaimer:** Operational GIS guidance only. This is not legal advice and not a substitute for title, survey, or counsel review.

## Jurisdiction split

Parcels in **King County (`53033`)** must be assigned to the zoning authority that controls the parcel:

- **`king_unincorporated`** for unincorporated county zoning.
- Seeded city jurisdictions below for parcels inside incorporated city limits.

Do not apply county zoning to city parcels or city zoning to unincorporated parcels. The overlay must emit `ZONING_JURISDICTION` explicitly.

## Countywide parcel and assessor source

| Purpose | Source | URL | Join / useful fields | Status |
|---------|--------|-----|----------------------|--------|
| Statewide parcel ingest | WaTech Washington State Parcels | https://geo.wa.gov/datasets/watech::washington-state-parcels-parcels-current/about | `FIPS_NR`, `PARCEL_ID_NR`, `APN`, situs aliases | baseline |
| County assessor/value/address enrichment | King County assessor roll | https://gismaps.kingcounty.gov/parcelviewer2/ | PIN; situs: TBD; mailing: TBD | source_found |

## Unincorporated county zoning source

| Jurisdiction | Source | URL | Zone fields | Status |
|--------------|--------|-----|-------------|--------|
| `king_unincorporated` | King County unincorporated zoning | https://gis-kingcounty.opendata.arcgis.com/datasets/kingcounty::zoning-for-unincorporated-king-county | CURRZONE;ZONING;ZONE | source_found |

Ordinance/use-table references to curate before trusting scores:

- King County Title 21A use tables


## Seeded city zoning sources

| Jurisdiction | City | Source URL | Ordinance/use table | Notes |
|--------------|------|------------|---------------------|-------|
| `seattle_city` | Seattle | TBD - official city zoning GIS/service | Seattle zoning/use table - TODO | Identify city GIS and ordinance use table. |
| `bellevue_city` | Bellevue | TBD - official city zoning GIS/service | Bellevue zoning/use table - TODO | Identify city GIS and ordinance use table. |
| `kent_city` | Kent | https://gis-cityofkent.opendata.arcgis.com/datasets/kent-zoning-districts | Kent zoning code and parking/use table | Kent zoning districts; see docs/zoning-sources-kent.md. |
| `renton_city` | Renton | TBD - official city zoning GIS/service | Renton zoning/use table - TODO | Identify city GIS and ordinance use table. |
| `federal_way_city` | Federal Way | TBD - official city zoning GIS/service | Federal Way zoning/use table - TODO | Identify city GIS and ordinance use table. |
| `kirkland_city` | Kirkland | TBD - official city zoning GIS/service | Kirkland zoning/use table - TODO | Identify city GIS and ordinance use table. |
| `redmond_city` | Redmond | TBD - official city zoning GIS/service | Redmond zoning/use table - TODO | Identify city GIS and ordinance use table. |
| `auburn_city` | Auburn | TBD - official city zoning GIS/service | Auburn zoning/use table - TODO | Identify city GIS and ordinance use table. |
| `burien_city` | Burien | TBD - official city zoning GIS/service | Burien zoning/use table - TODO | Identify city GIS and ordinance use table. |
| `shoreline_city` | Shoreline | TBD - official city zoning GIS/service | Shoreline zoning/use table - TODO | Identify city GIS and ordinance use table. |

## Workflow into this repository

1. Download or query the county and city zoning polygon layers.
2. Split parcels by city boundary / unincorporated area before assigning zoning.
3. Spatially join parcel centroid or parcel polygon to the controlling jurisdiction layer.
4. Emit an overlay GeoJSON with:
   - `COUNTY_FIPS`: `53033`
   - `ZONING`: normalized local zone code
   - `ZONING_JURISDICTION`: one of the jurisdiction keys above
   - optional `ZONING_ALLOWS_SURFACE_PARKING`: only when ordinance/legal review explicitly approves it
5. Update `data/zoning/wa/wa_county_surface_parking_rules.yaml` with curated zone mappings.
6. Move governance status from `not_started` only after source, use table, and sample parcel QA pass.

## Current scoring stance

The generated rules file keeps `default_when_unknown: false` and leaves this county's `zones` empty until curation. Unknown codes get no by-right surface-parking credit.

## Related files

- `docs/zoning-sources-king.md`
- `data/zoning/wa/wa_county_surface_parking_rules.yaml`
- `data/zoning/governance.yaml`
- `data/jurisdictions/wa/source_catalog.csv`
- `data/jurisdictions/wa/address_source_chains.yaml`
- `data/jurisdictions/wa/address_field_maps.yaml`
