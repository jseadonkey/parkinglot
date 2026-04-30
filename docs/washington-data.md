# Washington pilot — public data entry points

Use licensed parcel vendors for production; these are **starting points** for King / Snohomish / Pierce research.

## County assessor & GIS (open / semi-open)

| County     | FIPS  | Notes |
|-----------|-------|--------|
| King      | 53033 | [King County GIS / parcel search](https://gismaps.kingcounty.gov/parcelviewer2/) |
| Snohomish | 53061 | County GIS / assessor portals (verify current URLs and ToS) |
| Pierce    | 53053 | County GIS / assessor portals |

## State business registry (entities)

- [Washington Secretary of State — Corporations](https://ccfs.sos.wa.gov/) for entity verification when enriching owners.

## Zoning

Zoning is **municipal** in Washington (city + county). Map county open GIS + city zoning layers per submarket; expect multiple sources for a Puget Sound-wide product.

## DigitalOcean region

There is **no Seattle DO datacenter**. Use **`sfo3`** (or `sfo2`) for lowest latency from Washington to DigitalOcean; droplet, managed Postgres, and Spaces should use the **same region slug** for simpler networking and Spaces colocation.

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
