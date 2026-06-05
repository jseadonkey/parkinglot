# Zoning sources — Baltimore County, MD

This is the Phase B runbook for Baltimore County (`24005`) parcels under the
County zoning layer. It mirrors the Baltimore City workflow but uses Baltimore
County GIS services.

## Authoritative GIS layers

| Layer | URL | Notes |
| --- | --- | --- |
| Tax parcels | `https://bcgisdata.baltimorecountymd.gov/arcgis/rest/services/Property/Property/MapServer/1` | Official County tax parcel layer. Stable parcel fields include `TAXPIN` and `PARCEL_ASSET_ID`; ingest prefixes APNs as `MD-BALT-CO-*`. |
| Zoning | `https://bcgisapps.baltimorecountymd.gov/arcgis/rest/services/MyNeighborhood/MapServer/51` | Official MyNeighborhood **Zoning** layer. Use `ZONE_DIST` as the overlay zoning label; `ZONE_CLASS` is the base class. |
| GIS program page | `https://www.baltimorecountymd.gov/departments/information-technology/gis` | County GIS portal / terms / open data entry point. |

The zoning layer reports fields such as `DIST_CODE`, `ZONE_CLASS`, `ZONE_DIST`,
and `URL`. `ZONE_DIST` carries suffixes/overlays (for example `BM AS MU`);
rules are keyed against exact `ZONE_DIST` labels where possible.

## Ordinance / policy references

- Baltimore County Zoning Review:
  `https://www.baltimorecountymd.gov/departments/pai/zoning`
- Baltimore County PAI Zoning Policy Manual:
  `https://www.baltimorecountymd.gov/files/Documents/Permits/Zoning/zoning%20policy%20manual%202023.pdf`

Important policy note: business or industrial parking in residential/office
transition contexts can require a use permit or special hearing. The rules YAML
therefore treats County commercial/industrial zones as **conditional review**
until counsel confirms where paid surface parking is permitted by right.

## Local Phase B build

```bash
make baltimore-county-phase-b-local
```

Equivalent manual steps:

```bash
python3 scripts/fetch_baltimore_county_parcels.py \
  -o data/baltimore/baltimore_county_parcels.geojson \
  --max-features 20000

python3 scripts/fetch_baltimore_zoning_districts.py \
  --county county \
  -o data/baltimore/baltimore_county_zoning_districts.geojson

python3 scripts/build_baltimore_zoning_overlay.py --county county

python3 scripts/validate_phase_b_overlay.py \
  data/baltimore/baltimore_county_zoning_overlay.geojson

python3 scripts/summarize_baltimore_zoning_tiers.py \
  -i data/baltimore/baltimore_county_zoning_overlay.geojson \
  --jurisdiction baltimore_county_unincorporated
```

## Required overlay properties

The builder emits:

| Property | Value |
| --- | --- |
| `APN` | Normalized County APN, prefixed `MD-BALT-CO-` |
| `COUNTY_FIPS` | `24005` |
| `ZONING` | `ZONE_DIST` from the County zoning layer |
| `ZONING_JURISDICTION` | `baltimore_county_unincorporated` |

## Rules stance

`data/zoning/md/baltimore_county_surface_parking_rules.yaml` is conservative:

- residential / resource conservation / rural / agricultural zones are excluded;
- business, manufacturing, office, service employment, and similar zones are
  marked `principal_use_symbol: CB` / conditional-review for prioritization;
- `allows_surface_parking: false` remains in place until counsel confirms a
  permitted-by-right principal parking-lot path for a specific zone.

This prevents unreviewed County parcels from receiving full zoning credit while
still surfacing commercially/industrially zoned parcels for operator/legal review.
