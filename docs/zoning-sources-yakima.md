# Zoning sources - Yakima County, WA

**Disclaimer:** Operational GIS guidance only. This is not legal advice and not a substitute for title, survey, or counsel review.

## Jurisdiction split

Parcels in **Yakima County (`53077`)** must be assigned to the zoning authority that controls the parcel:

- **`yakima_unincorporated`** for unincorporated county zoning.
- Seeded city jurisdictions below for parcels inside incorporated city limits.

Do not apply county zoning to city parcels or city zoning to unincorporated parcels. The overlay must emit `ZONING_JURISDICTION` explicitly.

## Countywide parcel and assessor source

| Purpose | Source | URL | Join / useful fields | Status |
|---------|--------|-----|----------------------|--------|
| Statewide parcel ingest | WaTech Washington State Parcels | https://geo.wa.gov/datasets/watech::washington-state-parcels-parcels-current/about | `FIPS_NR`, `PARCEL_ID_NR`, `APN`, situs aliases | baseline |
| County assessor/value/address enrichment | Yakima County assessor roll | https://maps.yakimacounty.us/server/rest/services/Assessor/Taxlots/FeatureServer | ASSESSOR_N;TAXLOT_N; situs: SITUS_ADDR;SITUS_CITY;SITUS_ZIP; mailing: MAILING_AD;MAILING_CI;MAILING_STATE;MAILING_ZIP | source_found |

## Unincorporated county zoning source

| Jurisdiction | Source | URL | Zone fields | Status |
|--------------|--------|-----|-------------|--------|
| `yakima_unincorporated` | Yakima County unincorporated zoning | https://maps.yakimacounty.us/server/rest/services/Planning/CountyZoning/MapServer/0 | ZONE;JURISDICT;STATUS;Description | source_found |

Ordinance/use-table references to curate before trusting scores:

- Yakima County Code Ch. 19.14 Allowable Land Use Table
- Yakima County Code Ch. 19.22 Parking and Loading


## Seeded city zoning sources

| Jurisdiction | City | Source URL | Ordinance/use table | Notes |
|--------------|------|------------|---------------------|-------|
| `yakima_city` | Yakima | https://gis.yakimawa.gov/citymap/ | Yakima Municipal Code Title 15 Table 4-1; Yakima Municipal Code Ch. 15.06 Off-street Parking and Loading | CityMap is the official City of Yakima parcel/zoning lookup; export/API path requires follow-up. |

## Workflow into this repository

1. Download or query the county and city zoning polygon layers.
2. Split parcels by city boundary / unincorporated area before assigning zoning.
3. Spatially join parcel centroid or parcel polygon to the controlling jurisdiction layer.
4. Emit an overlay GeoJSON with:
   - `COUNTY_FIPS`: `53077`
   - `ZONING`: normalized local zone code
   - `ZONING_JURISDICTION`: one of the jurisdiction keys above
   - optional `ZONING_ALLOWS_SURFACE_PARKING`: only when ordinance/legal review explicitly approves it
5. Update `data/zoning/wa/wa_county_surface_parking_rules.yaml` with curated zone mappings.
6. Move governance status from `not_started` only after source, use table, and sample parcel QA pass.

## Current scoring stance

The generated rules file keeps `default_when_unknown: false` and leaves this county's `zones` empty until curation. Unknown codes get no by-right surface-parking credit.

## Related files

- `docs/zoning-sources-yakima.md`
- `data/zoning/wa/wa_county_surface_parking_rules.yaml`
- `data/zoning/governance.yaml`
- `data/jurisdictions/wa/source_catalog.csv`
- `data/jurisdictions/wa/address_source_chains.yaml`
- `data/jurisdictions/wa/address_field_maps.yaml`
