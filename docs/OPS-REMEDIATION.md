# Ops remediation loop

An automated **listen → diagnose → fix** agent that complements the [site watchdog](SITE-WATCHDOG.md).

| Agent | Focus |
|-------|--------|
| **Site watchdog** | Is the site up? API, UI, Postgres, Redis ping, queue depth |
| **Ops remediation** | Is **Baltimore priority data** healthy? Missing scores, demand distance, POI density, Celery workers |

## Schedule (UTC)

Runs on the **Slack Celery queue** every **6 hours** at **:15** (`OPS_REMEDIATION_CRONTAB_HOUR=*/6`, `OPS_REMEDIATION_CRONTAB_MINUTE=15`), alongside the hourly site watchdog.

Requires **`worker-slack`** and **`beat`** containers running.

## What it detects

- **Celery workers down** (tasks stuck `PENDING`) — critical, Slack alert, no auto-fix
- **Site watchdog failures** — re-runs watchdog
- **Baltimore City (`24510`)** gaps: missing demand distance, entitlement scores, OSM POI counts
- **Pipeline funnel backlog** — enqueues limited pipeline jobs when workers are healthy
- **Parking queue very deep** — same pipeline enqueue (cooldown applies)

## Auto-fix actions (with cooldown)

| Action | Default cooldown | What it does |
|--------|------------------|--------------|
| `refresh_demand_process_all` | 1h | Celery: demand distances, no identification rescore |
| `refresh_entitlement_process_all` | 1h | Celery: entitlement rescore for city |
| `refresh_poi_batch` | 1h | Celery: 50 parcels POI/Overpass (slow; repeats each run) |
| `enqueue_incomplete_limited` | 1h | Inline: up to 50 pipeline jobs |
| `run_site_watchdog` | 1h | Celery: site watchdog |

Set `OPS_REMEDIATION_AUTO_FIX=false` to **report only** (Slack still alerts on critical issues).

POI refresh uses **per-parcel commits + deadlock retry** — safe while other workers are active.

## Configuration (`deploy/.env`)

```bash
OPS_REMEDIATION_ENABLED=true
OPS_REMEDIATION_AUTO_FIX=true
OPS_REMEDIATION_PRIORITY_COUNTY_FIPS=24510
OPS_REMEDIATION_COOLDOWN_SEC=3600
OPS_REMEDIATION_POI_BATCH_LIMIT=50
OPS_REMEDIATION_PIPELINE_ENQUEUE_LIMIT=50
OPS_REMEDIATION_CRONTAB_HOUR=*/6
OPS_REMEDIATION_CRONTAB_MINUTE=15
# Optional dedicated Slack channel; else agents/digest channel
# OPS_REMEDIATION_SLACK_CHANNEL_ID=C...
```

## Manual runs

```bash
curl -sS -X POST https://api.vspecialist.com/internal/ops/run-now \
  -H "X-Internal-Key: $INTERNAL_API_KEY"

curl -sS https://api.vspecialist.com/internal/ops/status \
  -H "X-Internal-Key: $INTERNAL_API_KEY"
```

## When more DigitalOcean resources help

This loop fixes **configuration and backlog** problems. Resize the droplet or Postgres when watchdog shows sustained CPU/RAM/disk pressure, not only because remediation reported missing data.
