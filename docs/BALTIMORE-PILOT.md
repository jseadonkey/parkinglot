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

{"auto_run_pipeline": true, "max_auto_pipeline": 100}
```

Omit `max_features` (or send `null`) for the normal full-city pull. Use `max_features`
only for explicit test slices.

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
- `baltimore_ingest_now` — full city ingest
- Do **not** use county ingest until county is re-enabled in `geo_markets.yaml`

## Zoning (Maryland — Article 32)

Parcel ingest from EGIS sets **APN + county FIPS** only. Entitlement scoring needs a **zoning district** on each row:

1. **Rules file:** `data/zoning/md/baltimore_city_surface_parking_rules.yaml` (merged with WA rules at ingest).
2. **GIS layer:** [CityView/Zoning_New](https://geodata.baltimorecity.gov/egis/rest/services/CityView/Zoning_New/MapServer/0) — export with `scripts/fetch_baltimore_zoning_districts.py`.
3. **Phase B:** `scripts/build_baltimore_zoning_overlay.py` → `data/baltimore/baltimore_city_zoning_overlay.geojson` → merge (see `docs/zoning-sources-baltimore.md`). On Droplet: GitHub Action **baltimore_zoning_overlay**.
4. **Jurisdiction:** `ZONING_JURISDICTION=baltimore_city` or auto-infer from FIPS `24510`.
5. **Counsel:** Table 10-301 — **CB** (conditional) districts are scored as **not allowed** unless you set `ZONING_ALLOWS_SURFACE_PARKING` on the overlay.

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

Local QA: `make baltimore-phase-b-local` or `python3 scripts/summarize_baltimore_zoning_tiers.py`.

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
