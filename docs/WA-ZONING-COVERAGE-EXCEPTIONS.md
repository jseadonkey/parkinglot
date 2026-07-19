# WA zoning coverage — true remaining gaps

After WAZA Phase B overlays plus PostGIS direct recovery
(`scripts/fill_missing_zoning_spatial.py`), most incorporated cities have a
`zoning_code`. What remains is mostly **not a pipeline bug**.

## Expected / structural

| County | FIPS | Why zoning stays empty |
|---|---|---|
| Ferry | `53019` | No traditional zoning districts; absent from WAZA by design |
| Unincorporated rural tracts statewide | various | WAZA often covers only city/UGA polygons; farm/forest parcels sit outside |

## Large residual buckets (need county GIS, not more WAZA)

These still have many missing `zoning_code` values after two WAZA recovery
passes. WAZA polygons exist for the county but do not cover most of the
missing parcels (verified with spatial probes):

- Whitman (`53075`) — WAZA covers city jurisdictions only (Pullman, etc.)
- Okanogan (`53047`) — WAZA covers a few towns + some unincorporated zones; most missing parcels fall outside those polygons
- Asotin (`53003`), Lincoln (`53043`), Grant (`53025`), Pend Oreille (`53051`), Adams (`53001`) — same pattern: city/UGA coverage, rural gaps

Next source for these is each county’s official zoning GIS layer (Phase B
`zoning_sources` / county source agent), not another WAZA pass.

## What the recovery did recover

- Pass 1 (point-on-surface): ~1,589 parcels
- Pass 2 (footprint intersect + make-valid): ~3,996 additional parcels
- Counties with fresh zoning are re-queued through
  `refresh_entitlement_scores_batch(process_all=True)` and
  `refresh_identification_scores_batch(process_all=True)`

## Operator view

Prospect shortlist still works on residual counties via:

1. WAZA provisional tier (`PV` from `WAZAZoneGeneral` COM/MXU/IND) where raw
   WAZA attributes already exist on the parcel
2. Vacant / underutilized suitability from assessor values
3. Demand proximity (county seats + OSM POI density)
