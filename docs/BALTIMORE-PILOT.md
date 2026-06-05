# Baltimore pilot (primary market)

Washington statewide WaTech ingest is intentionally **slow** (size-based county cooldown, lower pipeline caps).
**Baltimore City and Baltimore County** are the active Maryland priorities for parcel ingest, scoring, and operator focus.

## Counties

| FIPS   | Jurisdiction      | Status        |
|--------|-------------------|---------------|
| 24510  | Baltimore City    | **Active**    |
| 24005  | Baltimore County  | **Active**    |

Config: `config/geo_markets.yaml`, `config/pilot_baltimore.yaml`, and Baltimore rows in `config/pilot.yaml`.

## Parcel sources

Baltimore City publishes parcels on EGIS ArcGIS:

- Layer: `Parcel_Information/Parcel/FeatureServer/0`
- Fetcher: `services/ingestion/parking_ingestion/baltimore_parcels.py` → `fetch_baltimore_city_geojson`

Baltimore County publishes parcels on County ArcGIS:

- Layer: `Property/Property/MapServer/1`
- Fetcher: `services/ingestion/parking_ingestion/baltimore_parcels.py` → `fetch_baltimore_county_geojson`

## Ingest (production API)

Queue a worker job (requires internal auth):

```http
POST /internal/ingest/baltimore-city
Content-Type: application/json

{"max_features": 20000, "auto_run_pipeline": true, "max_auto_pipeline": 100}
```

County:

```http
POST /internal/ingest/baltimore-county
Content-Type: application/json

{"max_features": 20000, "auto_run_pipeline": true, "max_auto_pipeline": 100}
```

Or upload / server-path GeoJSON with `default_county_fips=24510`.

Local export:

```bash
python3 scripts/fetch_baltimore_city_parcels.py -o data/baltimore/baltimore_city_parcels.geojson
python3 scripts/fetch_baltimore_county_parcels.py -o data/baltimore/baltimore_county_parcels.geojson --max-features 20000
```

## Operator UI

`GET /internal/stats/pilot-scope` includes `primary_market_*` and `priority_county_fips`. Scheduled priority pipeline enqueues **24510** and **24005** before Washington counties.

## Droplet ops

GitHub Actions → **Droplet resources**:

- `prioritize_baltimore_market` — geo config + priority pipeline.
- `baltimore_ingest_now` — city ingest (20k cap).
- County ingest is available through `POST /internal/ingest/baltimore-county` and local scripts.

## Zoning (Maryland)

Parcel ingest from EGIS sets **APN + county FIPS** only. Entitlement scoring needs a **zoning district** on each row:

1. **Rules files:** `data/zoning/md/baltimore_city_surface_parking_rules.yaml` and `data/zoning/md/baltimore_county_surface_parking_rules.yaml` (merged with WA rules at ingest).
2. **City GIS layer:** [CityView/Zoning_New](https://geodata.baltimorecity.gov/egis/rest/services/CityView/Zoning_New/MapServer/0) — export with `scripts/fetch_baltimore_zoning_districts.py`.
3. **County GIS layer:** [MyNeighborhood/Zoning](https://bcgisapps.baltimorecountymd.gov/arcgis/rest/services/MyNeighborhood/MapServer/51) — export with `scripts/fetch_baltimore_zoning_districts.py --county county`.
4. **Phase B City:** `make baltimore-phase-b-local` → `data/baltimore/baltimore_city_zoning_overlay.geojson` → merge (see `docs/zoning-sources-baltimore.md`).
5. **Phase B County:** `make baltimore-county-phase-b-local` → `data/baltimore/baltimore_county_zoning_overlay.geojson` → merge (see `docs/zoning-sources-baltimore-county.md`).
6. **Jurisdiction:** `baltimore_city` for FIPS `24510`; `baltimore_county_unincorporated` for FIPS `24005`.
7. **Counsel:** City **CB** districts and County commercial/industrial conditional-review districts should not receive full zoning credit unless counsel approves a specific path or overlay override.

Until Phase B completes, Baltimore parcels score **0** on the zoning weight (`default_when_unknown: false`).

## Entitlement tiers (Article 32)

Principal **surface parking lot** uses are classified in `data/zoning/md/baltimore_city_surface_parking_rules.yaml`:

| Tier | Meaning | Scoring |
|------|---------|---------|
| **Permitted (P)** | By-right principal parking | Full zoning weight (35 pts) |
| **Conditional (CB)** | BMZA hearing | Partial credit (12 pts) in Baltimore pilot |
| **Council (CO)** | Mayor & Council ordinance | 0 unless overlay override |
| **Excluded** | Not listed (most R-1–R-4) | 0 |

Operator console: filter parcels by **Zoning tier** on the Parcels page. API: `GET /internal/parcels/scored-list?zoning_tier=permitted&county_fips=24510`.

**Droplet GitHub Actions** (workflow *Droplet resources*):

| Input | What it does |
|-------|----------------|
| `baltimore_zoning_overlay` | Fetch GIS → build overlay → merge → entitlement rescore → priority enqueue |
| `baltimore_rescore_zoning` | Merge **existing** overlay only (after rules YAML update) + entitlement rescore |

Monitor live DB tier mix: `GET /internal/stats/baltimore-zoning-tiers`.

Local QA: `make baltimore-phase-b-local`, `make baltimore-county-phase-b-local`, or `python3 scripts/summarize_baltimore_zoning_tiers.py`.

## Revenue estimates (comps + demand)

Improve **Est. gross** on Baltimore parcels when nearby paid parking comps are sparse:

1. **Rate comps** — `POST /internal/rate-comps/seed-baltimore-pilot` (16 metro benchmarks in Postgres).
2. **Demand distance** — `POST /internal/metrics/refresh-demand-distances?county_fips=24510&limit=2000&process_all=true` (tier A + tier B YAML: `config/demand_generators_baltimore*.yaml`).
3. **Entitlement rescore** — `POST /internal/metrics/refresh-entitlement-scores?county_fips=24510&limit=2000&process_all=true`.
4. **OSM POI density** — `POST /internal/metrics/refresh-poi-density?county_fips=24510&limit=50` (repeat batches; Overpass ~1 req/sec).

**Overpass on Droplet:** set `POI_OVERPASS_URL=https://overpass.openstreetmap.fr/api/interpreter` in `deploy/.env` (default in compose). `overpass-api.de` is often unreachable from DigitalOcean.

**POI background fill:** `nohup bash scripts/refresh_baltimore_poi_loop.sh &` — log: `/tmp/baltimore-poi-refresh.log`.

**One-shot on Droplet:** `bash scripts/refresh_baltimore_revenue_signals.sh` (demand + entitlement sequential; POI via loop above)

**GitHub Actions → Droplet resources:** check **`refresh_baltimore_revenue_signals`** (all three steps + readiness snapshot).

See [TOP-PARCEL-DEAL-CONTEXT.md](TOP-PARCEL-DEAL-CONTEXT.md).

## Washington pacing

`config/wa_statewide_rollout.yaml` — size-based cooldown between counties (`min_days_base` / `min_days_per_10k_parcels` / `min_days_max`), reduced caps. WaTech county list is **WA-only** (FIPS `53*`).
