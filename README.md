# Parking acquisition agents

Multi-service system to score pilot parcels for paid parking suitability, enrich owner context, produce deal memos and contract drafts, with **human approval gates** before any outbound communication or contract execution.

CI runs on pushes and pull requests via [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

**Pilot region:** Washington State — Puget Sound counties (King, Snohomish, Pierce) in [`config/pilot.yaml`](config/pilot.yaml). Public GIS entry points: [`docs/washington-data.md`](docs/washington-data.md).

## Quick start (local)

1. Copy environment: `cp .env.example .env`
2. Start stack: `docker compose up --build`
3. API: http://localhost:8000/docs  
4. Load sample parcels: `curl -X POST http://localhost:8000/internal/ingest/sample`
5. Run pipeline for a parcel id from the response: `curl -X POST http://localhost:8000/parcels/<id>/pipeline/run`
6. Watch progress: `GET http://localhost:8000/workflow-runs?parcel_id=<uuid>` and `GET http://localhost:8000/internal/tasks/<task_id>` (internal key if set) — see [docs/OPERATIONS.md](docs/OPERATIONS.md).
7. Approval UI: http://localhost:3000

Postgres + PostGIS, Redis, Celery worker, MinIO (S3-compatible for Spaces), FastAPI, Next.js.

## Layout

- `config/pilot.yaml` — pilot FIPS, deal type, scoring weights, compliance flags
- `packages/core` — shared Pydantic models and pilot config loader
- `services/ingestion`, `scoring`, `enrichment`, `workflows` — domain packages
- `services/api` — HTTP API and Alembic migrations
- `services/worker` — Celery workers
- `apps/approval-ui` — internal approval app
- `infra/terraform` — DigitalOcean Managed Postgres, Spaces, Droplet baseline

## Production (DigitalOcean, 24/7)

Infrastructure as code: [infra/terraform/README.md](infra/terraform/README.md) (Managed Postgres, Spaces, Droplet, SSH + HTTP firewall, DB app user `parking_api`).

**Washington go-live runbook** (DNS, TLS, `.env`, compose): [docs/GO-LIVE-WASHINGTON-DO.md](docs/GO-LIVE-WASHINGTON-DO.md).

Production compose (no laptop required): [deploy/README.md](deploy/README.md). **On the Droplet** the repo usually lives at **`/opt/parking-acquisition-agents`** (override with `REMOTE_PATH` / `DROPLET_REMOTE_PATH` — see that README).

Closest DO region to Washington is **`sfo3`** (no Seattle datacenter); use the same region for Droplet, Postgres, and Spaces.

## Operations

Production runbook: [docs/OPERATIONS.md](docs/OPERATIONS.md) (health vs ready, logs, deploy scripts, uptime checks).

**Shortcuts:** `make help` (see [Makefile](Makefile)).

**CI deploy:** GitHub Actions → Droplet over SSH — [docs/GITHUB-DEPLOY.md](docs/GITHUB-DEPLOY.md).

**GHCR (pre-built images):** [docs/GHCR-DEPLOY.md](docs/GHCR-DEPLOY.md) — API-only or full stack (`make prod-up-ghcr`, `make prod-up-ghcr-full`). **Security:** [SECURITY.md](SECURITY.md).

**Dependabot:** [`.github/dependabot.yml`](.github/dependabot.yml) for Actions updates.

**Slack (optional):** 4-hour digest to a channel via Celery Beat + worker — [docs/SLACK.md](docs/SLACK.md). Local env merge: `make slack-env-local` (export `SLACK_BOT_TOKEN` and `SLACK_DIGEST_CHANNEL_ID` first).

## Legal

Templates and outreach require counsel review per [docs/compliance-checklist.md](docs/compliance-checklist.md).
