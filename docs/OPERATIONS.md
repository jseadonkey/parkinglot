# Operations (production)

## Health and uptime

- **Liveness**: `GET /health` — process up (no dependency checks).
- **Readiness**: `GET /ready` — can query Postgres (use for DigitalOcean Uptime checks, Kubernetes probes, etc.).

In DigitalOcean: **Monitoring → Uptime → Create check** → URL `https://<API_HOST>/ready`, expect status **200**.

If Caddy publishes **HTTPS on a non‑443 port** (for example **9443** when another service owns **443**), use that full URL in the check (for example `https://<API_HOST>:9443/ready`) and expect **200** after you accept **internal TLS** or front the service with a public certificate.

**UFW:** when using alternate Caddy ports, allow them explicitly (for example **`ufw allow 9080/tcp`** and **`ufw allow 9443/tcp`**). Helper: [`scripts/droplet-open-caddy-alt-ports-ufw.sh`](../scripts/droplet-open-caddy-alt-ports-ufw.sh).

From GitHub (no SSH to your laptop): **Actions → Droplet endpoint checks** curls **`/health`**, **`/ready`**, and optionally **`/internal/slack/status`** from the Droplet (same DNS/TLS path as production). See [GITHUB-DEPLOY.md](GITHUB-DEPLOY.md).

## Logs (Droplet)

```bash
cd /opt/workspaces/parkinglot
# (Legacy path on some hosts: `/opt/parking-acquisition-agents` — see docs/PROJECT-FACTS.md.)
# Managed Postgres only (default production compose):
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env logs -f --tail=200 api worker beat caddy

# On-droplet PostGIS addon (when deploy/.env has POSTGRES_PASSWORD — same pair as USE_LOCAL_POSTGIS=1):
docker compose -f deploy/docker-compose.production.yml -f deploy/docker-compose.postgis-addon.yml --env-file deploy/.env logs -f --tail=200 api worker beat postgres caddy
```

Slack digests (optional): [docs/SLACK.md](SLACK.md). Trigger a digest immediately with `POST /internal/slack/digest-now` (same auth as other `/internal/*` routes).

Compose uses **log rotation** (`max-size` / `max-file`) to avoid filling the disk.

## Pipeline and Celery visibility

- **Workflow runs (DB):** `GET /workflow-runs` — latest runs across parcels (optional query `parcel_id=<uuid>&limit=50`). `GET /workflow-runs/{run_id}` — one run (`status`, `current_step`, `error`, timestamps). Convenience: `GET /parcels/{parcel_id}/workflow-runs` (404 if parcel missing). Same data the worker writes while `run_pipeline` executes; use **OpenAPI** (`/docs`) for exact shapes.
- **Celery task state (Redis result backend):** `GET /internal/tasks/{task_id}` with the `task_id` returned from `POST /internal/ingest/sample` or `POST /parcels/{id}/pipeline/run`. Requires `X-Internal-Key` when `INTERNAL_API_KEY` is set in `.env`. Response includes `state` (`PENDING`, `STARTED`, `SUCCESS`, `FAILURE`, …), `ready`, and on failure `error` / `traceback` (traceback may be truncated).
- **Slack digest configured?** `GET /internal/slack/status` — booleans only (no secrets). See [docs/SLACK.md](SLACK.md).

For a full picture, combine **worker logs**, **`/workflow-runs`**, **`/approvals`**, and **`/audit`**.

## Owner outreach (SOS / vendor)

- **Read stored brief:** `GET /parcels/{parcel_id}/outreach` (404 until a pipeline or recompute has written `owner_outreach_brief`).
- **Recompute without full pipeline:** `POST /parcels/{parcel_id}/outreach/recompute` with JSON body `fetch_sos`, `fetch_sos_detail`, `call_vendor` (booleans). Async variant: `.../outreach/recompute/async` → poll `GET /internal/tasks/{task_id}`.
- **Pipeline-time HTTP (optional):** set `OUTREACH_PIPELINE_FETCH_SOS`, `OUTREACH_PIPELINE_FETCH_SOS_DETAIL`, and/or `OUTREACH_PIPELINE_CALL_VENDOR_WEBHOOK` to `true` so each `run_pipeline` builds the brief with the same integrations (use sparingly: rate limits and vendor cost).
- **Vendor webhook:** `OUTREACH_VENDOR_WEBHOOK_URL`, optional `OUTREACH_VENDOR_WEBHOOK_SECRET`, `OUTREACH_VENDOR_TIMEOUT_SEC`. **SOS client:** `OUTREACH_HTTP_USER_AGENT`, `OUTREACH_WA_SOS_TIMEOUT_SEC`.
- **Draft outbound messages (no sending):** `POST /parcels/{parcel_id}/outreach/message-draft` with JSON body `{ "channels": ["email","certified_mail"], "create_approval": true }`. This stores `parcels.outbound_message_drafts` and (optionally) creates a pending `ApprovalRequest(type=outbound_message)`.
- **Pipeline-time message draft approvals (optional):** set `OUTREACH_PIPELINE_CREATE_MESSAGE_APPROVAL=true` to automatically create an `outbound_message` approval during `run_pipeline`. Configure sender identity via `OUTREACH_SENDER_NAME`, `OUTREACH_SENDER_COMPANY`, `OUTREACH_SENDER_EMAIL`, `OUTREACH_SENDER_PHONE`.

## Deploy updates from your laptop

1. `git push` your changes (or ensure local tree matches what you want on the server).
2. `./scripts/sync-to-droplet.sh` (set `DROPLET`; optional `REMOTE_PATH` / `SSH_USER` — default remote path is `/opt/workspaces/parkinglot`).
3. `./scripts/remote-rebuild.sh`

For **GHCR-only** stacks, push new images from CI first, then on the Droplet `docker compose -f deploy/docker-compose.production.ghcr.yml --env-file deploy/.env pull && ... up -d` (or use the full GHCR compose) — see [GHCR-DEPLOY.md](GHCR-DEPLOY.md).

## Secrets rotation

- Rotate **`INTERNAL_API_KEY`**: update `deploy/.env`, then `docker compose ... up -d` (API + worker pick up env on recreate).
- Rotate **Spaces keys** or **database password**: update DO resources, then `.env`, then recreate `api` and `worker` containers.

## Backups

- **Managed Postgres**: enable automated backups in the DigitalOcean control panel; test restore in a non-production cluster periodically.
- **Spaces**: versioning is optional; drafts are reproducible from DB metadata plus pipeline re-runs where acceptable.
