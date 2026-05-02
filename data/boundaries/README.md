# Administrative boundaries (GeoJSON)

Stable references for **spatial filters** (e.g. “only score parcels inside Kent”). These files are **not** zoning layers—zoning portals and URLs can change without affecting these boundaries.

## Layout

| Path | Area | Source |
|------|------|--------|
| `wa/kent_city_census_places.geojson` | Kent city, King County, WA | US Census **TIGERweb** Incorporated Places (cartographic), layer **25**, query `BASENAME='Kent' AND STATE='53'` → **GEOID 5335415** |

## Refreshing the Kent polygon

Census updates boundaries periodically. To replace the file:

1. Open [TIGERweb Places / Incorporated Places](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/25/query) (same MapServer **layer 25**).
2. Query (GET): `where=BASENAME='Kent'+AND+STATE='53'`, `f=geojson`, `outSR=4326`.
3. Confirm **one** feature: **Kent city**, **GEOID** matching current Census place ID for Kent, WA (verify on data.census.gov if needed).
4. Save over `wa/kent_city_census_places.geojson`, keep `properties` notes in sync, commit.

## Container path

Production compose mounts repo `data/` at **`/app/data`**. Use:

`/app/data/boundaries/wa/kent_city_census_places.geojson`

when implementing SQL/API filters that intersect parcel geometries with this boundary.
