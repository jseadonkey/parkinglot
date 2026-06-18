# Washington statewide rollout (slow)

**Paused by default** when `WA_STATEWIDE_ROLLOUT_ENABLED=false`. Use **`enable_slow_statewide_expansion`** on the Droplet to turn on a **capacity-gated county loop** while **keeping the priority pipeline** for top entitlement parcels.

Prioritize **top entitlement parcels** (deal context + `SCHEDULED_PRIORITY_PIPELINE_*`) — statewide ingest runs in parallel at a low rate, not instead of it.

Adds **one new county at a time** from the public **WaTech** statewide parcel layer when the Celery **parking** queue is not overloaded and the load governor says capacity is healthy enough. **Wait time before the next county scales with how many parcels the last county loaded**; an hourly Beat tick checks whether the next county can start. King County is skipped once it already has rows in Postgres.

## How it works

| Piece | Role |
|-------|------|
| **`config/wa_statewide_rollout.yaml`** | County priority (Puget Sound first), pipeline cap per ingest, queue guard |
| **Beat** `wa_statewide_rollout_tick` | Hourly at **:15 UTC** by default; skips when cooldown/load/pending-ingest guards are active |
| **Worker** `fetch_watech_county_and_ingest` | Streams WaTech ArcGIS pages into `ingest_geojson_path` and writes completion audit totals |
| **Existing enqueue** | `SCHEDULED_ENQUEUE_*` continues draining pipeline backlog on loaded counties |

Default caps (tunable in `config/wa_statewide_rollout.yaml`):

- **15** parcels get `run_pipeline` per new county ingest batch (`max_auto_pipeline`)
- Skip a new county if **parking** queue depth **> 400**
- Skip a duplicate start while the most recently started county has not landed rows yet (`pending_ingest_lock_days`, default **0.1**)
- **Size-based cooldown** after each county (not a flat 7 days for everyone):
  - `min_days_base` (default **0.1**)
  - `+ min_days_per_10k_parcels` × (parcels in last county ÷ 10,000) (default **0.005**)
  - capped at `min_days_max` (default **0.5**)
  - Examples: ~5k parcels → ~0.1 days; ~50k → ~0.12 days; ~120k → ~0.16 days

## Enable on the Droplet

**Recommended (slow expansion + priority pipeline):**

```bash
# GitHub Actions → Droplet resources → enable_slow_statewide_expansion = true
```

This sets `WA_STATEWIDE_ROLLOUT_ENABLED=true`, checks hourly at `:15`, keeps `SCHEDULED_PRIORITY_PIPELINE_ENABLED=true`, caps backlog enqueue at 75, and kickstarts the next county if the queue is healthy.

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
GET  /internal/ingest/wa-rollout-status   # counties loaded vs remaining + zoning follow-up queue
POST /internal/ingest/wa-rollout-now      # start next county now (if queue OK)
```

From GitHub Actions: **Droplet resources** → `wa_rollout_status`, `zoning_followup_report`, or `wa_rollout_now`.

After each county's parcel count becomes non-zero, the `zoning_followup` block on
`wa-rollout-status` flags that county until the WA jurisdiction registry shows
trusted zoning coverage (`qa_passed` / `curated`) for its registered city and
unincorporated jurisdictions. The command-line equivalent is:

```bash
make zoning-followup-report
```

On the Droplet, that target uses `DATABASE_URL`; in GitHub Actions the
`zoning_followup_report` input feeds live rollout JSON into the same reporter.

## Benton lesson: prove rows, not just starts

Do not treat `wa_statewide_county_ingest` as proof of ingest completion. That audit
means the rollout loop **started** a county. Benton (`53005`) exposed why this
matters: the old all-at-once fetch/handoff path repeatedly recorded starts but no
rows landed.

The worker now streams WaTech in pages and calls `ingest_geojson_path` per page.
This gives durable partial progress (2k-row chunks) and writes
`wa_statewide_county_ingest_completed` with `pages_ingested`, `inserted`,
`updated`, `skipped`, and `parcel_features`.

When diagnosing a county:

1. Check `/internal/ingest/wa-rollout-status` for `parcels_in_db`.
2. Check latest `wa_statewide_county_ingest_completed` audit for page/row totals.
3. If there are repeated starts but no completion audit and no rows, inspect worker
   logs and retry with the chunked worker path before advancing to the next county.

## Benton zoning follow-up (after parcel load)

Once Benton parcels land (~30k rows), prescreen scores stay low until zoning is merged.
WaTech parcels do not include zoning; the next step is Phase B overlay merge:

```bash
make benton-zoning-fetch      # cache Kennewick/Pasco/Benton County GIS
make benton-zoning-overlay    # build data/benton/benton_county_zoning_overlay.geojson
make phase-b-run              # merge on Droplet (DATABASE_URL + PHASE_B_OVERLAY_PATH)
```

See `docs/zoning-sources-benton.md` for source URLs, join keys, and registry status.
Tri-Cities demand POIs in `config/pilot_identification.yaml` improve demand scoring after
zoning credit is attached.

**Scheduled merge:** enable `WA_PHASE_B_ROLLOUT_ENABLED=true` on the Droplet
(see `docs/WA-PHASE-B-ROLLOUT.md`). The hourly Beat loop runs Phase B when load
governor and queue depth allow — same capacity gates as parcel ingest.

## Progress expectation

- **~38 counties** remain after King (~124k parcels already loaded).
- **Pace varies by county size** — many small counties can load in quick succession; large Puget Sound counties space out by hours. Full statewide **ingest** advances continuously as long as queue/load guards stay healthy.
- **Scoring, zoning overlay, and outreach** still run on their own schedules — this only spreads **GIS ingest** across the state.

Do **not** enable `EXPLORATION_CAMPAIGN_ENABLED` at the same time unless you also place GeoJSON files under `data/exploration/` — rollout uses WaTech directly.

## Next county order (first few)

1. Pierce `53053`
2. Snohomish `53061`
3. Kitsap `53035`
4. Thurston `53067`
5. … (full list in `config/wa_statewide_rollout.yaml`)
