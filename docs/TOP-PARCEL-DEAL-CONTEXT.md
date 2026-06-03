# Top-parcel deal context (nearby + revenue)

Operator focus: enrich **highest entitlement scores** before statewide ingest.

## What you get

On each parcel page (`/operator/parcels/{id}`):

- **Parking rate comps** — YAML (`config/pilot.yaml` `parking_rate_comps`) merged with Postgres `parking_rate_comps` within `parking_rate_comp_radius_m` (default 2500m).
- **Illustrative gross revenue** — layout-based stall range × distance/similarity-weighted nearby hourly rate × hours × occupancy, then **discounted** when there are too few comps or the nearest comp is far away (same logic reduces the parking-market score). Shows confidence tier and unadjusted amount when discounted.
- **Nearby qualified parcels** — other lots with entitlement ≥ pilot floor within the same radius.

API: `GET /parcels/{parcel_id}/deal-context`

## Priority pipeline

Beat task **`enqueue_priority_qualified_scheduled`** (when enabled):

- Every **2 hours** at :20 UTC
- Up to **75** parcels per run
- Only prescreen-qualified with entitlement ≥ floor
- **Highest entitlement score first**

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

## Outreach board revenue column

`GET /internal/pipeline/outreach-board` includes full illustrative revenue (stall range, weighted hourly rate, monthly gross) for **all qualified rows** in the filtered region (`revenue_hints=0` default). Operator **Outreach** page shows **Est. gross** with stall and rate detail.

`GET /internal/parcels/scored-list` supports `include_revenue=true` (default), `qualified_only=true`, and state/county filters so **high-scoring parcels in any pilot region** get the same revenue analysis on the **Parcels** table.
