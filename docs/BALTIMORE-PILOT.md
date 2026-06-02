# Baltimore pilot (primary market)

Washington statewide WaTech ingest is intentionally **slow** (7-day county cooldown, lower pipeline caps). **Baltimore City** is the active priority for parcel ingest, scoring, and operator focus.

**Baltimore County (24005) is paused** — still listed in `config/pilot.yaml` for later, but not in `geo_markets.yaml` priority or automated county ingest.

## Counties

| FIPS   | Jurisdiction      | Status        |
|--------|-------------------|---------------|
| 24510  | Baltimore City    | **Active**    |
| 24005  | Baltimore County  | Paused        |

Config: `config/geo_markets.yaml`, `config/pilot_baltimore.yaml`, and Baltimore rows in `config/pilot.yaml`.

## Parcel source (city)

Baltimore City publishes parcels on EGIS ArcGIS:

- Layer: `Parcel_Information/Parcel/FeatureServer/0`
- Fetcher: `services/ingestion/parking_ingestion/baltimore_parcels.py` → `fetch_baltimore_city_geojson`

## Ingest (production API)

Queue a worker job (requires internal auth):

```http
POST /internal/ingest/baltimore-city
Content-Type: application/json

{"max_features": 20000, "auto_run_pipeline": true, "max_auto_pipeline": 100}
```

Or upload / server-path GeoJSON with `default_county_fips=24510`.

Local export:

```bash
python3 scripts/fetch_baltimore_city_parcels.py -o data/baltimore_city_parcels.geojson
```

## Operator UI

`GET /internal/stats/pilot-scope` includes `primary_market_*` and `priority_county_fips` (city only). Scheduled priority pipeline enqueues **24510** before Washington counties.

## Droplet ops

GitHub Actions → **Droplet resources**:

- `prioritize_baltimore_market` — geo config + priority pipeline; kicks **city** ingest only
- `baltimore_ingest_now` — city ingest only (20k cap)
- Do **not** use county ingest until county is re-enabled in `geo_markets.yaml`

## Washington pacing

`config/wa_statewide_rollout.yaml` — `min_days_between_counties: 7`, reduced caps. WaTech county list is **WA-only** (FIPS `53*`).
