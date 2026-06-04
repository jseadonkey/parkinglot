# Washington statewide rollout (slow)

**Paused by default** when `WA_STATEWIDE_ROLLOUT_ENABLED=false`. Use **`enable_slow_statewide_expansion`** on the Droplet to turn on **one county per day** while **keeping the priority pipeline** for top entitlement parcels.

Prioritize **top entitlement parcels** (deal context + `SCHEDULED_PRIORITY_PIPELINE_*`) — statewide ingest runs in parallel at a low rate, not instead of it.

Adds **one new county at a time** from the public **WaTech** statewide parcel layer when the Celery **parking** queue is not overloaded. **Wait time before the next county scales with how many parcels the last county loaded** (small counties can advance in ~1 day; King-scale counties wait longer). King County is skipped once it already has rows in Postgres.

## How it works

| Piece | Role |
|-------|------|
| **`config/wa_statewide_rollout.yaml`** | County priority (Puget Sound first), pipeline cap per ingest, queue guard |
| **Beat** `wa_statewide_rollout_tick` | Daily at **07:15 UTC** (default) |
| **Worker** `fetch_watech_county_and_ingest` | Downloads county GeoJSON from WaTech → `ingest_geojson_path` |
| **Existing enqueue** | `SCHEDULED_ENQUEUE_*` continues draining pipeline backlog on loaded counties |

Default caps (tunable in `config/wa_statewide_rollout.yaml`):

- **15** parcels get `run_pipeline` per new county ingest batch (`max_auto_pipeline`)
- Skip a new county if **parking** queue depth **> 400**
- **Size-based cooldown** after each county (not a flat 7 days for everyone):
  - `min_days_base` (default **0.5**)
  - `+ min_days_per_10k_parcels` × (parcels in last county ÷ 10,000) (default **0.75**)
  - capped at `min_days_max` (default **10**)
  - Examples: ~5k parcels → ~1 day; ~50k → ~4 days; ~120k → ~9.5 days

## Enable on the Droplet

**Recommended (slow expansion + priority pipeline):**

```bash
# GitHub Actions → Droplet resources → enable_slow_statewide_expansion = true
```

This sets `WA_STATEWIDE_ROLLOUT_ENABLED=true`, keeps `SCHEDULED_PRIORITY_PIPELINE_ENABLED=true`, caps backlog enqueue at 75, and kickstarts the next county if the queue is healthy.

**Rollout only (no priority tweak):**

```bash
# GitHub Actions → Droplet resources → enable_wa_statewide_rollout = true
```

Or merge into `deploy/.env`:

```bash
WA_STATEWIDE_ROLLOUT_ENABLED=true
WA_STATEWIDE_ROLLOUT_CONFIG_PATH=/app/config/wa_statewide_rollout.yaml
SCHEDULED_PRIORITY_PIPELINE_ENABLED=true
```

Restart **worker** + **beat** after deploy (new API image includes the task).

## Manual / status

```bash
GET  /internal/ingest/wa-rollout-status   # counties loaded vs remaining
POST /internal/ingest/wa-rollout-now      # start next county now (if queue OK)
```

From GitHub Actions: **Droplet resources** → `wa_rollout_status` or `wa_rollout_now`.

## Progress expectation

- **~38 counties** remain after King (~124k parcels already loaded).
- **Pace varies by county size** — many small counties can load in quick succession; large Puget Sound counties space out automatically. Full statewide **ingest** is typically **weeks**, not one fixed county per calendar week.
- **Scoring, zoning overlay, and outreach** still run on their own schedules — this only spreads **GIS ingest** across the state.

Do **not** enable `EXPLORATION_CAMPAIGN_ENABLED` at the same time unless you also place GeoJSON files under `data/exploration/` — rollout uses WaTech directly.

## Next county order (first few)

1. Pierce `53053`
2. Snohomish `53061`
3. Kitsap `53035`
4. Thurston `53067`
5. … (full list in `config/wa_statewide_rollout.yaml`)
