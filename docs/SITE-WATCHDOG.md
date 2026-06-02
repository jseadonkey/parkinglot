# Site watchdog agent

A **dedicated uptime agent** that checks the **public website**, **API**, and **Droplet server** on a fixed schedule. It runs in the cloud when your laptop is off.

This is **not** the Slack pipeline digest (`slack_agent_digest`), which reports parcel ingest/scoring activity on an hourly schedule and can feel inconsistent for “is the site up?” questions.

## What it checks

| Check | Where it runs |
|-------|----------------|
| `GET /health` | Droplet Celery + GitHub Actions (external) |
| `GET /ready` (Postgres) | Droplet Celery + GitHub Actions (external) |
| Operator UI `/operator` | Droplet Celery + GitHub Actions (external) |
| Postgres `SELECT 1` | Droplet Celery |
| Redis ping + parking queue depth | Droplet Celery |
| Root disk usage | GitHub Actions (SSH host `df`, not inside API container) |
| Docker compose container health | GitHub Actions (SSH host `docker compose ps`, not inside API container) |

**Note:** A `compose_health` detail of `No such file or directory: 'docker'` meant the old check ran inside the API container (fixed in `droplet-remote-checks.sh`). **`disk_root` at ≥90% is a real ops issue** — free space on the Droplet (see below).

## Schedules (UTC)

| Runner | Schedule | Slack |
|--------|----------|-------|
| **Celery Beat** → `worker-slack` | `:00` each hour (UTC) | Alert on failure/recovery; optional “all clear” every 1h when healthy |
| **GitHub Actions** `site-watchdog.yml` | `:10` and `:40` each hour | Alert on any failure |
| **Admin UI smoke** (existing) | `:15` every 6h | Logged-in browser tour |

## Slack

Messages go to the first configured channel:

1. `SITE_WATCHDOG_SLACK_CHANNEL_ID` (optional)
2. `SLACK_AGENT_DISCUSSION_CHANNEL_ID` (e.g. `#gf-parkinglot-agents-chat`)
3. `SLACK_DIGEST_CHANNEL_ID`

Alerts use plain text (not the pipeline Block Kit digest).

## Configuration (`deploy/.env`)

```bash
SITE_WATCHDOG_ENABLED=true
SITE_WATCHDOG_UI_BASE_URL=https://vspecialist.com
# Optional: dedicated channel; else agents or digest channel
# SITE_WATCHDOG_SLACK_CHANNEL_ID=C...
SITE_WATCHDOG_PARKING_QUEUE_WARN=50000
SITE_WATCHDOG_HEARTBEAT_HOURS=1
SITE_WATCHDOG_CRONTAB_MINUTE=0
```

## Manual runs

```bash
# Enqueue on Droplet (needs INTERNAL_API_KEY)
curl -sS -X POST https://api.vspecialist.com/internal/watchdog/run-now \
  -H "X-Internal-Key: $INTERNAL_API_KEY"

# Last result
curl -sS https://api.vspecialist.com/internal/watchdog/status \
  -H "X-Internal-Key: $INTERNAL_API_KEY"

# GitHub Actions → workflow "Site watchdog" → Run workflow
```

## Droplet disk full (`disk_root` ≥90%)

The root volume is small (~48G on many DO droplets). Large GeoJSON under `data/baltimore/` and Docker images/layers fill it quickly.

**Automated (no UI click required after deploy):**

| Runner | Schedule | Behavior |
|--------|----------|----------|
| **Droplet disk maintenance** (`droplet-disk-maintenance.yml`) | Sunday 06:15 UTC | Prune Docker; drop Baltimore staging GeoJSON when overlay exists |
| **Site watchdog** (`site-watchdog.yml`) | `:10`, `:40` each hour | If `disk_root` fails, runs the same maintenance script before Slack alert |

**Manual if needed:**

1. **Droplet resources** → **`disk_maintenance`** (or workflow **Droplet disk maintenance** with **aggressive**).
2. **`relieve_load`** if the Celery queue is huge.
3. **`droplet-cleanup-isolate`** for a heavier reset (recreates stack + aggressive prune when disk ≥85%).
4. **Droplet resources → `grow_disk`** after resizing the volume in DigitalOcean.

## Related docs

- [SLACK.md](./SLACK.md) — pipeline digest and qualified-parcel reports
- [UI-SMOKE-AGENT.md](./UI-SMOKE-AGENT.md) — Playwright admin UI checks
- [OPERATIONS.md](./OPERATIONS.md) — deploy and droplet ops
