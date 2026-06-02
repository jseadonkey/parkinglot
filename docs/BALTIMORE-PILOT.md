# Baltimore pilot (primary market)

Washington statewide WaTech ingest is intentionally **slow** (7-day county cooldown, lower pipeline caps). **Baltimore City and Baltimore County** are the top priority for parcel ingest, scoring, and operator focus.

## Counties

| FIPS   | Jurisdiction      |
|--------|-------------------|
| 24510  | Baltimore City    |
| 24005  | Baltimore County  |

Config: `config/geo_markets.yaml`, `config/pilot_baltimore.yaml`, and Baltimore rows in `config/pilot.yaml`.

## Parcel sources

| Jurisdiction | Source | Layer |
|--------------|--------|-------|
| Baltimore City | EGIS ArcGIS | `Parcel_Information/Parcel/FeatureServer/0` |
| Baltimore County | County GIS | `Property/Property/MapServer/1` |

Fetcher: `services/ingestion/parking_ingestion/baltimore_parcels.py`

## Ingest (production API)

Queue worker jobs (requires internal auth):

```http
POST /internal/ingest/baltimore-city
POST /internal/ingest/baltimore-county
Content-Type: application/json

{"max_features": 20000, "auto_run_pipeline": true, "max_auto_pipeline": 100}
```

GitHub Actions → **Droplet resources** → `baltimore_markets_ingest` runs both plus priority pipeline enqueue.

Or upload / server-path GeoJSON with `default_county_fips=24510`.

Local export:

```bash
python3 scripts/fetch_baltimore_city_parcels.py -o data/baltimore_city_parcels.geojson
```

## Operator UI

`GET /pilot/scope` includes `primary_market_*` and `priority_county_fips`. Scheduled priority pipeline enqueues **24510** and **24005** before Washington counties.

## Washington pacing

`config/wa_statewide_rollout.yaml` — `min_days_between_counties: 7`, reduced `max_auto_pipeline` / queue caps. WaTech county list is **WA-only** (FIPS `53*`); Maryland is never picked by the statewide rollout task.
