# Enable Washington statewide ingest (operator)

After API/worker deploy, turn WaTech county loading back on without pausing Baltimore priority pipeline.

## One GitHub Action run

**Actions → Droplet resources (via Droplet)** → Run workflow:

| Input | Set to |
|-------|--------|
| **enable_slow_statewide_expansion** | true |
| **wa_rollout_status** | true (same run prints county progress + cooldown) |

This will:

- Set `WA_STATEWIDE_ROLLOUT_ENABLED=true`
- Keep `SCHEDULED_PRIORITY_PIPELINE_ENABLED=true` (top deals still enqueue every 2h)
- Restart **worker** + **beat**
- Call **wa-rollout-now** if the parking queue is healthy

## Pacing (size-based, not one week per county)

Configured in `config/wa_statewide_rollout.yaml`:

- Wait after each county ≈ **0.5 days + 0.05 × (parcels ÷ 10,000)**, capped at **2 days**
- Small county (~5k parcels) → ~0.5 days before the next
- Large county (~120k parcels) → ~1.1 days
- Skips starting a county if **parking queue > 400**

## Check progress later

Same workflow with only:

- **wa_rollout_status** = true

Or from the Droplet (needs `INTERNAL_API_KEY`):

```bash
curl -sS https://api.vspecialist.com/internal/ingest/wa-rollout-status \
  -H "X-Internal-Key: $INTERNAL_API_KEY"
```

Look for `counties_remaining`, `next_county_fips`, `cooldown_ready`, and `last_ingested_county_parcels`.

## Do not run at the same time

- **prioritize_baltimore_market** — sets `WA_STATEWIDE_ROLLOUT_ENABLED=false` (pauses WA)

## Deploy code first

Sync/rebuild the Droplet so size-based cooldown and UI fixes are live:

```bash
make droplet-sync
make droplet-rebuild
```

Or **Actions → Deploy to Droplet** (GHCR compose).
