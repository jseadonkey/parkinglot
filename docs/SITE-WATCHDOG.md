# Site watchdog agent

A **dedicated uptime agent** that checks the **public website**, **API**, and **Droplet server** on a fixed schedule. It runs in the cloud when your laptop is off.

This is **not** the Slack pipeline digest (`slack_agent_digest`), which reports parcel ingest/scoring activity every 20 minutes and can feel inconsistent for “is the site up?” questions.

## What it checks

| Check | Where it runs |
|-------|----------------|
| `GET /health` | Droplet Celery + GitHub Actions (external) |
| `GET /ready` (Postgres) | Droplet Celery + GitHub Actions (external) |
| Operator UI `/operator` | Droplet Celery + GitHub Actions (external) |
| Postgres `SELECT 1` | Droplet Celery |
| Redis ping + parking queue depth | Droplet Celery |
| Root disk usage | GitHub Actions (SSH) |
| Docker compose container health | GitHub Actions (SSH) |

## Schedules (UTC)

| Runner | Schedule | Slack |
|--------|----------|-------|
| **Celery Beat** → `worker-slack` | `:05` and `:35` each hour | Alert on failure/recovery; optional “all clear” every 12h |
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
SITE_WATCHDOG_HEARTBEAT_HOURS=12
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

## Related docs

- [SLACK.md](./SLACK.md) — pipeline digest and qualified-parcel reports
- [UI-SMOKE-AGENT.md](./UI-SMOKE-AGENT.md) — Playwright admin UI checks
- [OPERATIONS.md](./OPERATIONS.md) — deploy and droplet ops
