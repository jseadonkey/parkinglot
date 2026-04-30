# Production deploy (DigitalOcean Droplet)

## Where the app lives on the Droplet

The repo is meant to sit in a single directory on the Droplet, with `docker compose` run from there so paths like `../config` in the compose files resolve correctly.

| Item | Value |
|------|--------|
| **Default path** | `/opt/parking-acquisition-agents` |
| **Folder name** | `parking-acquisition-agents` (matches the git clone / rsync target) |

You can use another path (e.g. `/home/deploy/app`); set **`REMOTE_PATH`** for [`scripts/sync-to-droplet.sh`](../scripts/sync-to-droplet.sh) and [`scripts/remote-rebuild.sh`](../scripts/remote-rebuild.sh), or GitHub variable **`DROPLET_REMOTE_PATH`** for [`.github/workflows/deploy-droplet.yml`](../.github/workflows/deploy-droplet.yml). If unset, those tools default to `/opt/parking-acquisition-agents`.

On the server, secrets live in **`deploy/.env`** next to the compose files (that file is never committed).

- **Compose file**: [`docker-compose.production.yml`](docker-compose.production.yml) — API, **Celery worker**, **Celery Beat** (schedules Slack digest among other periodic tasks), Redis, approval UI, Caddy (TLS). Uses **Managed Postgres** and **Spaces** (no container database or MinIO).
- **Slack (optional):** [docs/SLACK.md](../docs/SLACK.md) — set `SLACK_BOT_TOKEN` and `SLACK_DIGEST_CHANNEL_ID` in `deploy/.env`.
- **Env template**: [`env.production.example`](env.production.example) → copy to `deploy/.env` on the server (gitignored).
- **Edge proxy**: [`Caddyfile`](Caddyfile) — `UI_HOST` and `API_HOST` must have DNS pointing at the Droplet before TLS will succeed.

Full Washington + DO steps: [docs/GO-LIVE-WASHINGTON-DO.md](../docs/GO-LIVE-WASHINGTON-DO.md).

Compose validation in CI uses committed dummy env: [`ci.env`](ci.env) (not for production).

Day-2 ops (logs, uptime, deploy from laptop): [docs/OPERATIONS.md](../docs/OPERATIONS.md).

Pre-built images from GHCR: [docs/GHCR-DEPLOY.md](../docs/GHCR-DEPLOY.md) · [`docker-compose.production.ghcr.yml`](docker-compose.production.ghcr.yml) (API+worker) · [`docker-compose.production.ghcr-full.yml`](docker-compose.production.ghcr-full.yml) (API+worker+UI).

From repository root:

```bash
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env up -d --build
```

Sync + rebuild from your laptop (requires SSH):

```bash
chmod +x scripts/sync-to-droplet.sh scripts/remote-rebuild.sh
DROPLET=<droplet-ipv4> ./scripts/sync-to-droplet.sh
DROPLET=<droplet-ipv4> ./scripts/remote-rebuild.sh
```

Slack env on the Droplet + restart worker/beat only: [`scripts/set-slack-env-on-droplet.sh`](../scripts/set-slack-env-on-droplet.sh) (see [docs/SLACK.md](../docs/SLACK.md)).
