# WA Phase B rollout (scheduled zoning overlay merge)

When **`WA_PHASE_B_ROLLOUT_ENABLED=true`**, Celery Beat runs **`wa_phase_b_rollout_tick`**
hourly (default minute `:45` UTC). The loop mirrors the parcel ingest rollout:

1. **Load governor** — skip when pressure is orange/red (same gate as parcel ingest).
2. **Queue depth** — skip when the parking Celery queue exceeds `max_parking_queue_depth`.
3. **Pending lock** — skip if a county merge started recently and has not completed.
4. **Cooldown** — wait `min_hours_between_county_merges` after the last successful merge.
5. **Pick next county** — first priority county with parcels loaded, zoning follow-up needed,
   missing zoning on ≥ `min_missing_zoning_pct` of rows, and an overlay builder or staged file.

For Benton (`53005`), the worker **builds the overlay automatically** (Kennewick attribute
join + Pasco/Benton County spatial joins) then calls **`merge_parcel_attributes_geojson`**.

## Enable on Droplet

```bash
# deploy/.env
WA_PHASE_B_ROLLOUT_ENABLED=true
WA_PHASE_B_ROLLOUT_CRONTAB_HOUR=*
WA_PHASE_B_ROLLOUT_CRONTAB_MINUTE=45
```

Restart **worker + beat** after changing env vars.

## Status / manual kick

```bash
GET  /internal/ingest/wa-phase-b-rollout-status
POST /internal/ingest/wa-phase-b-rollout-now
```

GitHub Actions: **Droplet resources** → `wa_phase_b_rollout_status` / `enable_wa_phase_b_rollout`
(when wired).

## Config

`config/wa_phase_b_rollout.yaml` — county priority, cooldowns, per-county overlay paths.

## Related

- `docs/zoning-sources-benton.md` — GIS sources for Benton overlay builder
- `docs/WA_STATEWIDE_ROLLOUT.md` — Phase A parcel ingest loop
- `scripts/execute-phase-b.sh` — one-shot manual merge runner
