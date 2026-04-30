# Operations (production)

## Health and uptime

- **Liveness**: `GET /health` — process up (no dependency checks).
- **Readiness**: `GET /ready` — can query Postgres (use for DigitalOcean Uptime checks, Kubernetes probes, etc.).

In DigitalOcean: **Monitoring → Uptime → Create check** → URL `https://<API_HOST>/ready`, expect status **200**.

From GitHub (no SSH to your laptop): **Actions → Droplet endpoint checks** curls **`/health`**, **`/ready`**, and optionally **`/internal/slack/status`** from the Droplet (same DNS/TLS path as production). See [GITHUB-DEPLOY.md](GITHUB-DEPLOY.md).

## Logs (Droplet)

```bash
cd /opt/parking-acquisition-agents
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env logs -f --tail=200 api worker beat caddy
```

Slack digests (optional): [docs/SLACK.md](SLACK.md). Trigger a digest immediately with `POST /internal/slack/digest-now` (same auth as other `/internal/*` routes).

Compose uses **log rotation** (`max-size` / `max-file`) to avoid filling the disk.

## Pipeline and Celery visibility

- **Workflow runs (DB):** `GET /workflow-runs` — latest runs across parcels (optional query `parcel_id=<uuid>&limit=50`). `GET /workflow-runs/{run_id}` — one run (`status`, `current_step`, `error`, timestamps). Convenience: `GET /parcels/{parcel_id}/workflow-runs` (404 if parcel missing). Same data the worker writes while `run_pipeline` executes; use **OpenAPI** (`/docs`) for exact shapes.
- **Celery task state (Redis result backend):** `GET /internal/tasks/{task_id}` with the `task_id` returned from `POST /internal/ingest/sample` or `POST /parcels/{id}/pipeline/run`. Requires `X-Internal-Key` when `INTERNAL_API_KEY` is set in `.env`. Response includes `state` (`PENDING`, `STARTED`, `SUCCESS`, `FAILURE`, …), `ready`, and on failure `error` / `traceback` (traceback may be truncated).
- **Slack digest configured?** `GET /internal/slack/status` — booleans only (no secrets). See [docs/SLACK.md](SLACK.md).

For a full picture, combine **worker logs**, **`/workflow-runs`**, **`/approvals`**, and **`/audit`**.

## Deploy updates from your laptop

1. `git push` your changes (or ensure local tree matches what you want on the server).
2. `./scripts/sync-to-droplet.sh` (set `DROPLET`, optional `REMOTE_PATH` / `SSH_USER`).
3. `./scripts/remote-rebuild.sh`

For **GHCR-only** stacks, push new images from CI first, then on the Droplet `docker compose -f deploy/docker-compose.production.ghcr.yml --env-file deploy/.env pull && ... up -d` (or use the full GHCR compose) — see [GHCR-DEPLOY.md](GHCR-DEPLOY.md).

## Secrets rotation

- Rotate **`INTERNAL_API_KEY`**: update `deploy/.env`, then `docker compose ... up -d` (API + worker pick up env on recreate).
- Rotate **Spaces keys** or **database password**: update DO resources, then `.env`, then recreate `api` and `worker` containers.

## Backups

- **Managed Postgres**: enable automated backups in the DigitalOcean control panel; test restore in a non-production cluster periodically.
- **Spaces**: versioning is optional; drafts are reproducible from DB metadata plus pipeline re-runs where acceptable.
