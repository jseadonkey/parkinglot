# Parking acquisition agents

Multi-service system to score pilot parcels for paid parking suitability, enrich owner context, produce deal memos and contract drafts, with **human approval gates** before any outbound communication or contract execution.

CI runs via [`.github/workflows/ci.yml`](.github/workflows/ci.yml): **pull requests** (all branches) and **pushes to `main`** (not duplicate runs on every PR push): **Ruff** (Python packages plus [`scripts/`](scripts/)), **pytest** for [`services/api`](services/api), a **`scripts/export_openapi_json.py`** step (writes and validates JSON; **artifact** `openapi` on the workflow run for download), Docker **smoke builds** for API + approval UI images, **Compose config** validation, and **`bash -n`** on shell helpers (phase runners and [`scripts/ci-api-local.sh`](scripts/ci-api-local.sh)). The **`test-api`** job **caches pip** from workspace `pyproject.toml` files to speed installs.

**Same checks on your laptop:** `make api-ci` or [`./scripts/ci-api-local.sh`](scripts/ci-api-local.sh). That mirrors **lint** + **`test-api`** (Ruff, pytest, then OpenAPI JSON export smoke — creates a `.venv` at the repo root on first run; requires network for `pip` until dependencies are installed). Pass through pytest options, e.g. `./scripts/ci-api-local.sh tests/test_openapi.py -v`.

**API contracts:** interactive docs at `/docs`, machine-readable schema at `/openapi.json`. [`services/api/tests/test_openapi.py`](services/api/tests/test_openapi.py) asserts routes and response schema refs stay aligned. To snapshot the schema (e.g. for codegen or diff), use **`make openapi-export`** or `python3 scripts/export_openapi_json.py` with the same Python env as **`make api-ci`**.

**Rollout vs repo:** [docs/PROCESS-COVERAGE.md](docs/PROCESS-COVERAGE.md) maps **scripted processes** vs **true externals** (counsel, vendors, county ToS). Phase status and checklists: [docs/PHASED-EXECUTION-PLAN-A-E.md](docs/PHASED-EXECUTION-PLAN-A-E.md), [docs/OPERATOR-TODO-BUNDLE.md](docs/OPERATOR-TODO-BUNDLE.md).

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
- `config/pilot_strategic.yaml` / `config/pilot_identification.yaml` — Beacon (pipeline) and Cartographer (ingest prescreen) scoring profiles
- `packages/core` — shared Pydantic models and pilot config loader
- `services/ingestion`, `scoring`, `enrichment`, `workflows` — domain packages
- `services/api` — HTTP API and Alembic migrations
- `services/worker` — Celery workers
- `apps/approval-ui` — internal approval app
- `infra/terraform` — DigitalOcean Managed Postgres, Spaces, Droplet baseline

## Production (DigitalOcean, 24/7)

Infrastructure as code: [infra/terraform/README.md](infra/terraform/README.md) (Managed Postgres, Spaces, Droplet, SSH + HTTP firewall, DB app user `parking_api`).

**Washington go-live runbook** (DNS, TLS, `.env`, compose): [docs/GO-LIVE-WASHINGTON-DO.md](docs/GO-LIVE-WASHINGTON-DO.md).

Production compose (no laptop required): [deploy/README.md](deploy/README.md). **On the Droplet** use repo root **`/opt/parking-acquisition-agents`** ([docs/DROPLET_REPO_PATH.md](docs/DROPLET_REPO_PATH.md); override with `REMOTE_PATH` / `DROPLET_REMOTE_PATH` if needed).

Closest DO region to Washington is **`sfo3`** (no Seattle datacenter); use the same region for Droplet, Postgres, and Spaces.

## Operations

Production runbook: [docs/OPERATIONS.md](docs/OPERATIONS.md) (health vs ready, logs, deploy scripts, uptime checks).

**Phased rollout:** [docs/PHASED-EXECUTION-PLAN-A-E.md](docs/PHASED-EXECUTION-PLAN-A-E.md). **Operator checklist:** [docs/OPERATOR-TODO-BUNDLE.md](docs/OPERATOR-TODO-BUNDLE.md).

**Shortcuts:** `make help`; `make process-coverage` → [docs/PROCESS-COVERAGE.md](docs/PROCESS-COVERAGE.md); **`make export-parcel-scores`**; **`make preflight-zoning`** / **`make phase-b-pipeline`** (Phase B); **`make slack-droplet-check`** / **`make slack-digest-wait`** (Slack ops); `make api-ci`; `make openapi-export`; `make operator-todos`.

**CI deploy:** GitHub Actions → Droplet over SSH — [docs/GITHUB-DEPLOY.md](docs/GITHUB-DEPLOY.md).

**GHCR (pre-built images):** [docs/GHCR-DEPLOY.md](docs/GHCR-DEPLOY.md) — API-only or full stack (`make prod-up-ghcr`, `make prod-up-ghcr-full`). **Security:** [SECURITY.md](SECURITY.md).

**Dependabot:** [`.github/dependabot.yml`](.github/dependabot.yml) for Actions updates.

**Slack (optional):** recurring digest to a channel every **20 minutes (UTC)** via Celery Beat + worker — [docs/SLACK.md](docs/SLACK.md). Local env merge: `make slack-env-local` (export `SLACK_BOT_TOKEN` and `SLACK_DIGEST_CHANNEL_ID` first).

## Legal

Templates and outreach require counsel review per [docs/compliance-checklist.md](docs/compliance-checklist.md).
