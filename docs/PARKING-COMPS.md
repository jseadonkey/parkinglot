# Parking comp market signal (Kent + unincorporated King pilot)

Strategic and identification scoring can use **curated paid parking comps** instead of illustrative POI demand generators.

## What it measures

For each parcel centroid we find the nearest comp in `data/pilot/kent_king_parking_comps.yaml` that meets the screening floor (`min_rate_usd_per_day`, default **$6/day**). We store:

- `distance_to_nearest_comp_parking_m` — great-circle meters to that comp
- `nearest_parking_comp` — JSON snapshot (name, kind, rates, distance)

## Scoring profiles

| Profile | Comp weight | POI fallback |
|---------|-------------|--------------|
| **Entitlement** (`pilot.yaml`) | 0 (disabled) | POI demand generators (400 m buffer) |
| **Strategic** (`pilot_strategic.yaml`) | 40 pts within 800 m | POI only if comp data missing |
| **Identification** (`pilot_identification.yaml`) | 20 pts within 800 m | POI fallback if comp missing |

Premium comps (≥ **$15/day**) earn the same points but notes call out the higher rate.

## Refresh after deploy

Parking comps are **not** computed at bulk ingest. They run when:

- `run_pipeline` sees entitlement ≥ pilot floor, surface zoning allowed, and building share ≤ 70%, or
- You enqueue **`POST /internal/metrics/refresh-parking-comps`** (same gates; entitlement-qualified only)

```bash
curl -sS -X POST "https://api.vspecialist.com/internal/metrics/refresh-parking-comps?limit=5000&county_fips=53033" \
  -H "X-Internal-Key: YOUR_INTERNAL_KEY"
```

Then re-run incomplete pipelines so entitlement/strategic scores pick up the new comp fields:

```bash
curl -sS -X POST "https://api.vspecialist.com/internal/pipeline/enqueue-incomplete?limit=500" \
  -H "X-Internal-Key: YOUR_INTERNAL_KEY"
```

## Updating comps

Edit `data/pilot/kent_king_parking_comps.yaml` — rates are **screening estimates**, not live feeds. After changes, run the refresh endpoint above.

## Operator UI

Parcel detail shows **Nearest parking comp** with distance and daily rate next to the legacy POI demand distance.
