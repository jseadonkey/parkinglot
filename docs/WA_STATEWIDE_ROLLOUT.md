# Washington statewide rollout (slow)

Adds **one new county per day** from the public **WaTech** statewide parcel layer when the Celery **parking** queue is not overloaded. King County is skipped once it already has rows in Postgres.

## How it works

| Piece | Role |
|-------|------|
| **`config/wa_statewide_rollout.yaml`** | County priority (Puget Sound first), pipeline cap per ingest, queue guard |
| **Beat** `wa_statewide_rollout_tick` | Daily at **07:15 UTC** (default) |
| **Worker** `fetch_watech_county_and_ingest` | Downloads county GeoJSON from WaTech → `ingest_geojson_path` |
| **Existing enqueue** | `SCHEDULED_ENQUEUE_*` continues draining pipeline backlog on loaded counties |

Default caps (tunable in YAML):

- **40** parcels get `run_pipeline` per new county ingest batch (`max_auto_pipeline`)
- Skip a new county if **parking** queue depth **> 800**

## Enable on the Droplet

```bash
# GitHub Actions → Droplet resources → enable_wa_statewide_rollout = true
```

Or merge into `deploy/.env`:

```bash
WA_STATEWIDE_ROLLOUT_ENABLED=true
WA_STATEWIDE_ROLLOUT_CONFIG_PATH=/app/config/wa_statewide_rollout.yaml
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
- **~1 county/day** ≈ statewide parcel **ingest** in about **5–6 weeks** if the queue stays healthy.
- **Scoring, zoning overlay, and outreach** still run on their own schedules — this only spreads **GIS ingest** across the state.

Do **not** enable `EXPLORATION_CAMPAIGN_ENABLED` at the same time unless you also place GeoJSON files under `data/exploration/` — rollout uses WaTech directly.

## Next county order (first few)

1. Pierce `53053`
2. Snohomish `53061`
3. Kitsap `53035`
4. Thurston `53067`
5. … (full list in `config/wa_statewide_rollout.yaml`)
