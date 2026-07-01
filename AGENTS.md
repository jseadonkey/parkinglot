# AGENTS.md

## Cursor Cloud specific instructions

Setup context for future cloud agents. The startup update script already creates the repo-root
Python venv (`.venv`) with all local packages + `ruff`, and installs `apps/approval-ui` node deps.
System packages (`python3.12-venv`, Docker CE) and Docker's `/etc/docker/daemon.json`
(fuse-overlayfs + `containerd-snapshotter` disabled) persist in the VM snapshot. Standard commands
live in `README.md`, `CONTRIBUTING.md`, and the `Makefile` (`make help`); notes below are only the
non-obvious caveats.

### Product
Multi-service system that scores land parcels for paid-parking suitability, enriches owner context,
and drafts deal memos/contracts behind **human approval gates**. Backend is Python 3.12
(FastAPI API + Celery workers + domain packages); frontend is Next.js 15 (`apps/approval-ui`,
`apps/operator-console`). Storage: PostgreSQL 16 + PostGIS, Redis (Celery), MinIO (S3).

### Lint & test (Python-only, no Docker needed)
- Preferred: `make run-api-tests` (bootstraps `uv` into `.uv-bin/`, runs mainline-parity + ruff + pytest).
- CI parity: `make api-ci` / `bash scripts/ci-api-local.sh` (ruff + pytest + OpenAPI export smoke).
- With the pre-installed `.venv` you can run directly without re-bootstrapping:
  - Lint: `.venv/bin/ruff check packages/core services/api/app services/scoring services/ingestion services/enrichment services/workflows services/api/tests scripts`
  - Tests: `cd services/api && ../../.venv/bin/python -m pytest -q` (pytest reads config from `services/api`; do not run from repo root).

### Running the full app stack (Docker Compose)
- The models require PostgreSQL + **PostGIS** and JSONB, so SQLite is not an option; the app cannot
  run without the compose services (postgres, redis, minio, api, worker).
- The Docker daemon is **not auto-started** (no systemd). Start it once per VM:
  `sudo dockerd > /tmp/dockerd.log 2>&1 &` (run in a tmux/background session), then wait for
  `sudo docker info` to succeed. `daemon.json` is already configured for this kernel.
- Bring up the stack: `cp .env.example .env` (once), then
  `sudo docker compose up -d postgres redis minio minio-init api worker`.
- The `api` container runs `alembic upgrade heads` on start, so no manual migration step is needed.
- **Host ports are remapped** by `docker-compose.override.yml`: API is on `http://localhost:18000`
  (not 8000) and the containerized approval-ui on `http://localhost:13000`. README examples use
  8000/3000 (the in-container ports).

### Hello-world / smoke flow
1. `curl -X POST http://localhost:18000/internal/ingest/sample` — enqueues a Celery ingest that
   auto-runs the pipeline (needs the `worker` container up).
2. Inspect: `GET /parcels`, `GET /parcels/<id>/score`, `GET /approvals?status=pending`.
3. A completed pipeline leaves the workflow run in status `blocked` / `awaiting_human` and creates a
   pending `contract_send` approval — this is the human gate, **not** an error.
4. Approve via API `POST /approvals/<id>/approve` or through the UI.

### approval-ui (dev mode)
- Run from `apps/approval-ui`: `API_SERVER_URL=http://localhost:18000 npm run dev` (serves on `:3000`).
- The browser talks to the API only through the same-origin proxy at `/api/proxy/...`, which allows
  just `approvals` and `outreach-templates` paths; set `API_SERVER_URL` so the proxy can reach the API.
- With `AUTH_SECRET` unset there is **no login** and approve/reject actions are enabled (dev default).
  Set `AUTH_SECRET` + `AUTH_ADMIN_EMAIL`/`AUTH_ADMIN_PASSWORD` to exercise the login flow.
- `next dev` rewrites `tsconfig.json` and `next-env.d.ts` on first run — do not commit those churn edits.

### Optional integrations
Slack, Lob (mail), Langfuse/OpenAI (the separate `services/crew` CLI) are all optional and disabled
without their env vars/secrets; the core pipeline and approval flow run fully without them.
