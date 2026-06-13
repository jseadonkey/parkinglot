# Top-parcel deal context (nearby + revenue)

Operator focus: enrich **highest entitlement scores** before statewide ingest.

## What you get

On each parcel page (`/operator/parcels/{id}`):

- **Parking rate comps** — YAML (`config/pilot.yaml` `parking_rate_comps`) merged with Postgres `parking_rate_comps` within `parking_rate_comp_radius_m` (default 2500m). If fewer than two comps are found, search repeats at **`parking_rate_comp_expanded_radius_m`** (default 7500m).
- **Illustrative gross revenue** — layout-based stall range × distance/similarity-weighted nearby hourly rate × hours × occupancy (`scoring.revenue_assumptions` in `config/pilot.yaml`), then **discounted** when there are too few comps or the nearest comp is far away (same logic reduces the parking-market score). Low/high bands use stall, rate, and occupancy ranges (not confidence alone). Assessor `lot_sqft` is capped at mapped **footprint** area when it is much larger. Optional **monthly net** subtracts configured land-rent and operator-margin % of gross mid.
- **No local comps** — when the expanded search still finds nothing, revenue uses **`parking_rate_fallbacks`** in `config/pilot.yaml` (county-specific or default indicative hourly rate) at **`confidence_factor`** (default 0.55). Tier shows as **`fallback`**; treat as directional only until real comps are seeded.
- **Nearby qualified parcels** — other lots with entitlement ≥ pilot floor within the same radius.

API: `GET /parcels/{parcel_id}/deal-context`

## Improving revenue when comps are sparse

| Priority | Action | Effect |
|----------|--------|--------|
| 1 | **Seed real comps** into Postgres (`parking_rate_comps`) | Best accuracy; Puget Sound: `POST /internal/rate-comps/seed-king-pilot`; **Baltimore:** `POST /internal/rate-comps/seed-baltimore-pilot` or `bash scripts/refresh_baltimore_revenue_signals.sh` on Droplet |
| 2 | **Tune county fallbacks** in `config/pilot.yaml` → `parking_rate_fallbacks.counties` | Unblocks revenue on rural/statewide parcels with zero nearby paid parking |
| 3 | **Expand radius** (`parking_rate_comp_expanded_radius_m`) | Pulls distant but directionally useful comps before falling back |
| 4 | **Operator-verified rates** | Replace illustrative YAML placeholders and fallback notes with rates from Metropolis, Diamond, PMS, etc. on actual sites |
| 5 | **Future: POI/vendor feed** | OSM `amenity=parking` + fee tags, ParkMobile zones, or commercial POI — see `docs/data-vendor-shortlist.md` |

Confidence tiers: **`high` / `moderate`** = trust for outreach ranking; **`low` / `very_low`** = comp exists but discounted; **`fallback`** = no local comps, county default rate only.

## Demand-based revenue (when comps are sparse)

**Rate** comes from nearby paid parking comps (or county fallback). **Volume** (occupancy) can be approximated separately from **demand generators** — points in `config/pilot.yaml` (`demand_generators`) for hospitals, downtown retail, stadiums, universities, etc.

| Signal | Used today | How |
|--------|------------|-----|
| **Distance to nearest demand POI** | Scoring + revenue | Stored on parcel as `distance_to_nearest_demand_m`; refresh via `POST /internal/metrics/refresh-demand-distances` |
| **Occupancy adjustment** | Revenue | Within `demand_generator_buffer_m` (default 400 m), occupancy scales up to ~1.05× base (55%); far sites scale down to ~0.35× |
| **Fallback + strong demand** | Revenue confidence | No rate comps but within demand buffer → small confidence uplift (still not “high”) |

**Not yet in code (future):** business customer counts, SafeGraph foot traffic, or “employees within 500 m” — POI density is the first automated layer.

### OSM commercial POI density (implemented)

OpenStreetMap counts **restaurants, shops, clinics, hotels, offices, etc.** within **`poi_demand.radius_m`** (default **400 m**) of each parcel centroid.

| Step | Action |
|------|--------|
| 1 | Run migration `0010` (`poi_commercial_count_400m` on `parcels`) |
| 2 | `POST /internal/metrics/refresh-poi-density?limit=50&county_fips=24510` — **~1 req/sec** to public Overpass (keep `limit` modest) |
| 3 | Revenue blends **generator distance + POI count** into `occupancy_effective` |

Readiness: `GET /internal/stats/export-readiness` → `parcels_missing_poi_commercial_count_400m`.

Env (optional): `POI_OVERPASS_URL` (default `https://overpass.openstreetmap.fr/api/interpreter` on Droplet — `overpass-api.de` often fails), `POI_OVERPASS_DELAY_SEC`, `POI_OVERPASS_USER_AGENT`.

### Expand demand POIs

Replace illustrative points with real submarkets. Categories that drive surface parking:

- Hospitals / medical campuses  
- Sports venues / arenas  
- Downtown / BID cores  
- Universities  
- Transit hubs (where park-and-ride spillover exists)  
- Major retail strips  

After editing demand POIs, update **`config/demand_generators_baltimore.yaml`** (tier A anchors) and/or **`config/demand_generators_baltimore_tier_b.yaml`** (large restaurants, grocery, big-box), then run:

- **`POST /internal/metrics/refresh-demand-distances?county_fips=24510&limit=2000&process_all=true`**
- **`POST /internal/metrics/refresh-entitlement-scores?county_fips=24510&limit=2000&process_all=true`**

(`process_all` requires a current API worker image; see `scripts/refresh_baltimore_revenue_signals.sh`.)

## Priority pipeline

Beat task **`enqueue_priority_qualified_scheduled`** (when enabled):

- Every **2 hours** at :20 UTC
- Up to **75** parcels per run
- Only prescreen-qualified lots with top owner-outreach scores by default (**Atlas ≥ 85**, then **Beacon ≥ 80**)
- **Highest entitlement score first**, then Beacon score

The score floors are configurable with `OWNER_OUTREACH_MIN_ENTITLEMENT_SCORE` and
`OWNER_OUTREACH_MIN_STRATEGIC_SCORE`. Broader Atlas/Beacon scoring can continue, but owner
outreach briefs are reserved for this high-score target cohort.

Enable on Droplet:

```bash
# GitHub Actions → Droplet resources → enable_priority_pipeline = true
# Or for statewide + priority together:
# enable_slow_statewide_expansion = true
```

Or:

```bash
SCHEDULED_PRIORITY_PIPELINE_ENABLED=true
WA_STATEWIDE_ROLLOUT_ENABLED=false   # or true with enable_slow_statewide_expansion
```

Manual burst:

```bash
POST /internal/pipeline/enqueue-priority?limit=75
```

## Adding real rate comps

**One-shot seed (19 Puget Sound garages/lots):**

```bash
POST /internal/rate-comps/seed-king-pilot
```

GitHub Actions → **Droplet resources** → `seed_king_rate_comps = true`.

Or insert rows into **`parking_rate_comps`** (PostGIS point + `hourly_mid_usd`) or extend `pilot.yaml`. Replace illustrative placeholders with operator-verified benchmarks.

**Baltimore metro (16 benchmarks):**

```bash
POST /internal/rate-comps/seed-baltimore-pilot
```

GitHub Actions → **Droplet resources** → `seed_baltimore_rate_comps = true`, or **`refresh_baltimore_revenue_signals = true`** (seed + demand distances + POI density in one run).

On the Droplet: `bash scripts/refresh_baltimore_revenue_signals.sh` (repeat until POI batch completes — ~50 parcels/minute).

## Outreach board revenue column

`GET /internal/pipeline/outreach-board` includes full illustrative revenue (stall range, weighted hourly rate, monthly gross) for **top-score owner-outreach target rows** in the filtered region (`revenue_hints=0` default). Operator **Outreach** page shows **Est. gross** with stall and rate detail.

`GET /internal/parcels/scored-list` supports `include_revenue=true` (default), `qualified_only=true`, and state/county filters so **high-scoring parcels in any pilot region** get the same revenue analysis on the **Parcels** table.
