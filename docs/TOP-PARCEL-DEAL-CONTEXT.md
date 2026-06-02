# Top-parcel deal context (nearby + revenue)

Operator focus: enrich **highest entitlement scores** before statewide ingest.

## What you get

On each parcel page (`/operator/parcels/{id}`):

- **Parking rate comps** — YAML (`config/pilot.yaml` `parking_rate_comps`) merged with Postgres `parking_rate_comps` within `parking_rate_comp_radius_m` (default 2500m).
- **Illustrative gross revenue** — median nearby hourly rate × estimated stalls × hours × occupancy (not a pro forma).
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
```

Or:

```bash
SCHEDULED_PRIORITY_PIPELINE_ENABLED=true
WA_STATEWIDE_ROLLOUT_ENABLED=false
```

Manual burst:

```bash
POST /internal/pipeline/enqueue-priority?limit=75
```

## Adding real rate comps

Insert rows into **`parking_rate_comps`** (PostGIS point + `hourly_mid_usd`) or extend `pilot.yaml` list. Replace illustrative Seattle placeholders with verified garage/lot benchmarks.
