# Washington pilot — public data entry points

Use licensed parcel vendors for production; these are **starting points** for King / Snohomish / Pierce research.

## County assessor & GIS (open / semi-open)

| County     | FIPS  | Notes |
|-----------|-------|--------|
| King      | 53033 | [King County GIS / parcel search](https://gismaps.kingcounty.gov/parcelviewer2/) |
| Snohomish | 53061 | County GIS / assessor portals (verify current URLs and ToS) |
| Pierce    | 53053 | County GIS / assessor portals |

### WaTech — Washington State Parcels (free statewide layer)

The **Washington State Parcels Project** publishes a **normalized** statewide parcel polygon layer (participating counties). Public **ArcGIS FeatureServer**:

`https://services.arcgis.com/jsIt88o09Q0r1j8h/arcgis/rest/services/Previous_Parcels/FeatureServer/0`

Overview: [Washington State Parcels on geo.wa.gov](https://geo.wa.gov/datasets/watech::washington-state-parcels-parcels-current/about).

**This repo**

- **CLI:** [`scripts/fetch_wa_opendata_parcels.py`](../scripts/fetch_wa_opendata_parcels.py) — writes county-filtered GeoJSON (`--max-features` caps trial pulls).
- **Worker:** `POST /internal/ingest/watech-county` — JSON `{"county_fips":"53033","max_features":5000,"auto_run_pipeline":true}` enqueues download + ingest. Poll `GET /internal/tasks/{fetch_task_id}`; result payload includes `ingest_task_id` when done.

Use **`max_features`** for short experiments; full counties require many paginated requests.

## State business registry (entities)

- [Washington Secretary of State — Corporations](https://ccfs.sos.wa.gov/) for entity verification when enriching owners.

## Zoning

Zoning is **municipal** in Washington (city + county). Map county open GIS + city zoning layers per submarket; expect multiple sources for a Puget Sound-wide product.

## DigitalOcean region

There is **no Seattle DO datacenter**. Use **`sfo3`** (or `sfo2`) for lowest latency from Washington to DigitalOcean; droplet, managed Postgres, and Spaces should use the **same region slug** for simpler networking and Spaces colocation.

## Submarket boundary (Kent city)

For **Kent-only** scoring without depending on zoning portal URLs, use the bundled **city limit** polygon:

- **`data/boundaries/wa/kent_city_census_places.geojson`** — Kent city incorporated place (EPSG:4326), sourced from US Census TIGERweb (see `data/boundaries/README.md` for refresh steps).

Intersect parcel footprints with this geometry in PostGIS (or pre-filter exports) to restrict pipelines to the south-end anchor city.

## Getting parcel lots into the app (GeoJSON)

1. Export or build a **polygon** GeoJSON **FeatureCollection** for parcels in pilot counties (`53033`, `53061`, `53053` — see `config/pilot.yaml`). Each feature should carry at least a parcel identifier and ideally lot size; the loader maps common column names (`APN`, `PIN`, `PARCEL_ID`, `COUNTY_FIPS`, `LOT_SQFT`, `CALC_ACRES` / `ACRES`, zoning flags — see `services/ingestion/parking_ingestion/geojson_loader.py`).
2. **Upload** (requires `X-Internal-Key` when `INTERNAL_API_KEY` is set):

   ```bash
   curl -sS -X POST "https://$API_HOST/internal/ingest/geojson-upload" \
     -H "X-Internal-Key: $INTERNAL_API_KEY" \
     -F "file=@/path/to/parcels.geojson" \
     -F "default_county_fips=53033" \
     -F "auto_run_pipeline=true" \
     -F "max_auto_pipeline=100"
   ```

   Use `default_county_fips` when the file has no `COUNTY_FIPS` on each feature. `auto_run_pipeline` enqueues scoring + downstream workflow (capped to avoid flooding the worker on huge files).

3. Poll **`GET /internal/tasks/{task_id}`** for the ingest task result (`inserted`, `updated`, `skipped`, `parcel_ids`).
4. List scored “qualified” lots (latest score ≥ `scoring.qualified_min_score` in `pilot.yaml`): **`GET /parcels?qualified_only=true`** or **`GET /parcels?min_score=60`**.

Re-ingesting the same **county + APN/PIN** updates geometry and attributes and clears the previous **score** so you can re-run the pipeline.

Verify **terms of use** for any county or vendor export before production use.

### Large files on the Droplet (server path)

If the GeoJSON is already on the machine (e.g. under `/opt/workspaces/parkinglot/data/`), enqueue ingest without uploading through the API:

```bash
curl -sS -X POST "https://$API_HOST/internal/ingest/geojson-server-path" \
  -H "X-Internal-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"path":"/opt/workspaces/parkinglot/data/king_parcels.geojson","default_county_fips":"53033","auto_run_pipeline":false}'
```

### Score parcels already in Postgres

After bulk ingest with `auto_run_pipeline=false`, enqueue pipelines for parcels that **have no score yet**:

```bash
curl -sS -X POST "https://$API_HOST/internal/pipeline/enqueue-unscored?limit=200" \
  -H "X-Internal-Key: $INTERNAL_API_KEY"
```

### Derived metrics at ingest

When properties omit **lot size**, the worker estimates **square feet from polygon area** (ellipsoidal geodesic). When **`DIST_DEMAND_M`** is absent but `scoring.demand_generators` lists `{lat, lon}` points in `pilot.yaml`, distance is filled from the parcel footprint **centroid** to the nearest POI (great-circle meters). Tune or replace those POIs for real submarkets.
