# Operations (production)

**Batch checklist (DNS, deploy, phases A–C, GIS/vendor backlog in one place):** [OPERATOR-TODO-BUNDLE.md](OPERATOR-TODO-BUNDLE.md).

**Web UI to browse parcels, workflow/deal status, approvals, readiness:** [OPERATOR-CONSOLE.md](OPERATOR-CONSOLE.md) (`https://<UI_HOST>/operator`).

## Health and uptime

- **Liveness**: `GET /health` — process up (no dependency checks).
- **Readiness**: `GET /ready` — can query Postgres (use for DigitalOcean Uptime checks, Kubernetes probes, etc.).

In DigitalOcean: **Monitoring → Uptime → Create check** → URL `https://<API_HOST>/ready`, expect status **200**.

If Caddy publishes **HTTPS on a non‑443 port** (for example **9443** when another service owns **443**), use that full URL in the check (for example `https://<API_HOST>:9443/ready`) and expect **200** after you accept **internal TLS** or front the service with a public certificate.

**UFW:** when using alternate Caddy ports, allow them explicitly (for example **`ufw allow 9080/tcp`** and **`ufw allow 9443/tcp`**). Helper: [`scripts/droplet-open-caddy-alt-ports-ufw.sh`](../scripts/droplet-open-caddy-alt-ports-ufw.sh).

From GitHub (no SSH to your laptop): **Actions → Droplet endpoint checks** curls **`/health`**, **`/ready`**, and optionally **`/internal/slack/status`** from the Droplet (same DNS/TLS path as production). See [GITHUB-DEPLOY.md](GITHUB-DEPLOY.md).

**Admin UI browser agent:** **Actions → Admin UI smoke (browser)** logs in as admin, visits operator pages, and posts failures to Slack (optional). Setup: [UI-SMOKE-AGENT.md](UI-SMOKE-AGENT.md).

## Logs (Droplet)

```bash
cd /opt/parking-acquisition-agents
# Canonical Droplet repo root — see [DROPLET_REPO_PATH.md](DROPLET_REPO_PATH.md) if your clone lives elsewhere.
# Managed Postgres only (default production compose):
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env logs -f --tail=200 api worker beat caddy

# On-droplet PostGIS addon (when deploy/.env has POSTGRES_PASSWORD — same pair as USE_LOCAL_POSTGIS=1):
docker compose -f deploy/docker-compose.production.yml -f deploy/docker-compose.postgis-addon.yml --env-file deploy/.env logs -f --tail=200 api worker beat postgres caddy
```

Slack digests (optional): [docs/SLACK.md](SLACK.md). Trigger a digest immediately with `POST /internal/slack/digest-now` (same auth as other `/internal/*` routes).

Compose uses **log rotation** (`max-size` / `max-file`) to avoid filling the disk.

**Scheduled disk maintenance:** GitHub Actions workflow **Droplet disk maintenance** (Sundays 06:15 UTC) prunes unused Docker data and removes Baltimore staging GeoJSON when the zoning overlay file already exists. **Site watchdog** runs the same script automatically when root disk is ≥90%. Manual: **Droplet resources** → `disk_maintenance`, or **Droplet cleanup and isolate** for a heavier reset. Details: [SITE-WATCHDOG.md](SITE-WATCHDOG.md).

## Pipeline and Celery visibility

- **Workflow runs (DB):** `GET /workflow-runs` — latest runs across parcels (optional query `parcel_id=<uuid>&limit=50`). `GET /workflow-runs/{run_id}` — one run (`status`, `current_step`, `error`, timestamps). Convenience: `GET /parcels/{parcel_id}/workflow-runs` (404 if parcel missing). Same data the worker writes while `run_pipeline` executes; use **OpenAPI** (`/docs`) for exact shapes.
- **Celery task state (Redis result backend):** `GET /internal/tasks/{task_id}` with the `task_id` returned from `POST /internal/ingest/sample` or `POST /parcels/{id}/pipeline/run`. Requires `X-Internal-Key` when `INTERNAL_API_KEY` is set in `.env`. Response includes `state` (`PENDING`, `STARTED`, `SUCCESS`, `FAILURE`, …), `ready`, and on failure `error` / `traceback` (traceback may be truncated).
- **Slack digest configured?** `GET /internal/slack/status` — booleans only (no secrets). See [docs/SLACK.md](SLACK.md).

For a full picture, combine **worker logs**, **`/workflow-runs`**, **`/approvals`**, and **`/audit`**.

## Parcels: ingest, score, and “agents”

End-to-end phased checklist (**CSV columns, zoning overlays, owner rollup, multi-county**): [PHASED-EXECUTION-PLAN-A-E.md](PHASED-EXECUTION-PLAN-A-E.md).

Scoring is **deterministic** from `config/pilot.yaml` (entitlement) and `config/pilot_strategic.yaml` (strategic). The worker runs **`run_pipeline`** per parcel; nothing “discovers” lots until **parcel rows exist** in Postgres.

1. **Load parcels (GeoJSON)**  
   - **Quick check:** from the Droplet, with `INTERNAL_API_KEY` in `deploy/.env`, call **`POST /internal/ingest/sample`**. This loads `data/sample_parcels.geojson` and, by default, **enqueues the full pipeline** (dual scores + workflow run).  
   - **Production:** `scp` a county export to the repo’s `data/` (mounted read-only at `/app/data/...` in containers) and call **`POST /internal/ingest/geojson-server-path`** with `auto_run_pipeline: true` in the JSON body, or set **`SCHEDULED_GEOJSON_INGEST_*`** in `deploy/.env` and **recreate** `worker` + **beat** so Beat can run `ingest_geojson_path` on a schedule. Compose must pass those variables (see `deploy/docker-compose.production*.yml`).

2. **Backfill scoring (Atlas + Beacon)**  
   - `POST /internal/pipeline/enqueue-unscored?limit=200` — parcels **missing entitlement** (`parcel_scores` with profile `entitlement`), up to 500.  
   - `POST /internal/pipeline/enqueue-incomplete?limit=200` — parcels missing **entitlement or strategic** (use after migrations or partial pipeline failures).  
   Celery Beat can run the same **incomplete-pair** logic on a schedule (parcels missing entitlement or strategic — every **4 hours** UTC when enabled — see **`SCHEDULED_ENQUEUE_*`** in `deploy/env.production.example`). Keep it disabled during resource pressure; restart **worker + beat** after changing those variables.

3. **Enrich attributes without replacing footprints** (zoning overlay, corner flags, demand distance on props)  
   After you spatially join zoning into GeoJSON (same property aliases as ingest — `ZONING`, `ZONING_JURISDICTION`, `IS_CORNER`, `DIST_DEMAND_M`, …), call **`POST /internal/ingest/merge-geojson-attributes`** with JSON `{"path":"/abs/path/overlay.geojson","refresh_pipeline":true}`. The **`path`** must be readable by the **worker** container as given (typically **`/app/data/...`** where repo **`data/`** is mounted). Dry-run counts with the same loader: **`python3 scripts/validate_phase_b_overlay.py /path/on/host.geojson`** (`make validate-phase-b-overlay`). Automated merge + readiness: [`scripts/execute-phase-b.sh`](../scripts/execute-phase-b.sh) — set **`PHASE_B_OVERLAY_PATH`** to that worker-visible path; if validation runs on the host copy only, set **`PHASE_B_OVERLAY_VALIDATE_PATH`** to the host file. Updates existing parcels only; refreshes Cartographer identification scores and optionally re-enqueues `run_pipeline`.  
   If **`PUBLIC_API_URL`** / DNS is not ready yet, run Phase B **inside** the **`api`** container so **`PHASE_B_API_BASE=http://127.0.0.1:8000`** works (see script header for `docker compose … exec api …`).

4. **Refresh demand distance from pilot POIs**  
   **`POST /internal/metrics/refresh-demand-distances?limit=2000`** recomputes centroid → nearest generator using **`config/pilot.yaml`** `demand_generators` (optional `county_fips=53033`). For each parcel updated in this batch, the worker also **re-upserts** the identification (Cartographer) score — but only for parcels **included** in the batch (recent-by-default ordering).

5. **Backfill identification only (Cartographer)**  
   When **`GET /internal/stats/export-readiness`** shows **`parcels_missing_score_identification`** but you do not need another demand-distance pass, call **`POST /internal/metrics/refresh-identification-scores?limit=2000`** (optional `county_fips=53033`). This Celery task upserts identification scores for parcels **missing** an identification `parcel_scores` row (no full re-ingest). Automated runner: [`scripts/execute-phase-a.sh`](../scripts/execute-phase-a.sh) (`PHASE_A_REFRESH_IDENTIFICATION`, `PHASE_A_IDENT_LIMIT`).

6. **Confirm**  
   `GET /internal/stats/scoring-summary` (same internal auth) — expect non-zero `total_parcels`, `parcels_with_latest_*_score`, and `qualified_count_*` once pipelines finish.  
   **`GET /internal/stats/export-readiness`** — null/gap **counts** for footprint, zoning, lot size, demand distance, and each score profile (stakeholder CSV dry-run). Poll **`GET /internal/tasks/{task_id}`** after async POSTs.

Pilot region filters are in **`config/pilot.yaml`** (`region.county_fips`). Features outside those counties are skipped at ingest.

### Parcel scores CSV (stakeholder feedback)

Export latest identification / entitlement / strategic scores per parcel (same profile strings as `app.scoring_profiles`) to a shareable CSV. Requires **`DATABASE_URL`** (same as the API) and the backend Python deps (`pip install -e services/api` from a venv at repo root, or run inside the **`api`** container where `/app` is the API package root). The script adds `services/api` to `sys.path` when run from the repo root, so extra **`PYTHONPATH`** is optional.

```bash
cd /opt/parking-acquisition-agents
export DATABASE_URL='postgresql+psycopg://...'
python3 scripts/check_export_readiness.py
# Optional: --json   ;   same authless DB URL as export
python3 scripts/export_scored_parcels_csv.py -o parcel_scores_export.csv
# Optional: --limit 500   ;   -o - for stdout   ;   in api container: PYTHONPATH=/app ...
```

- **Public HTTPS link (DigitalOcean Spaces)** — same **`STORAGE_*`** variables as the API (`STORAGE_ENDPOINT`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `STORAGE_BUCKET`, `STORAGE_REGION`). After export, upload with **`--publish-spaces`** (alias **`--upload-public`**). The script prints the **HTTPS URL on stdout** (one line); **`public-read` exposes parcel data** — use only for non-sensitive pilots. Example:
  `DATABASE_URL=... STORAGE_ENDPOINT=https://sfo3.digitaloceanspaces.com ... python3 scripts/export_scored_parcels_csv.py --publish-spaces -o parcel_scores_export.csv`

For **satellite / map visual review** of a scored shortlist (Google Maps, OpenStreetMap, King County parcel viewer link where applicable), use [`scripts/parcel_visual_review_sheet.py`](../scripts/parcel_visual_review_sheet.py) and see [visual-site-review.md](visual-site-review.md). The API image includes `/app/scripts` after rebuild; otherwise run the script from a repo checkout with the same `DATABASE_URL`.

### Washington 7-day exploration campaign (optional)

Use this when you want Celery Beat to **pull county GeoJSON files from disk on a daily rotation** over a fixed **7-day calendar window** (counts toward statewide coverage; data acquisition is still **your** GeoJSON exports).

1. **County parcels:** Place one GeoJSON file per county under repo **`data/exploration/`** on the Droplet (mounted at **`/app/data/exploration/`** in containers), named **`{county_fips}.geojson`** (e.g. `53033.geojson`). Missing files are skipped that day and listed in worker logs.
2. **`deploy/.env`:** Set **`EXPLORATION_CAMPAIGN_ENABLED=true`**, **`EXPLORATION_CAMPAIGN_START_DATE=YYYY-MM-DD`** (first day of the 7-day window, UTC), optionally **`EXPLORATION_CAMPAIGN_CRONTAB_HOUR`** / **`EXPLORATION_CAMPAIGN_CRONTAB_MINUTE`** (default **06:30 UTC**). Omit **`EXPLORATION_CAMPAIGN_START_DATE`** until you are ready; empty values are treated as unset.
3. **Restart `worker` and `beat`** after changing env so **`celery_app`** reloads Beat entries.
4. **Logs:** `docker compose … logs -f beat worker` — look for **`exploration_campaign_tick`** and **`WA exploration campaign`**.

This does **not** download assessor data automatically; it only ingests files you stage. **`config/exploration_campaign_wa.yaml`** controls **`duration_days`** (default **7**), path template, and **`max_auto_pipeline_per_county`**.

## Owner outreach (SOS / vendor)

- **Gap counts:** `python3 scripts/check_export_readiness.py` includes **`parcels_missing_owner_outreach_brief`** (Phase C), scoped only to top-score owner-outreach targets. Defaults: **Atlas ≥ 85** and **Beacon ≥ 80** (`OWNER_OUTREACH_MIN_ENTITLEMENT_SCORE`, `OWNER_OUTREACH_MIN_STRATEGIC_SCORE`). Smoke portfolio internals + readiness: [`scripts/execute-phase-c.sh`](../scripts/execute-phase-c.sh) (`make phase-c-run`, optional **`PHASE_C_OWNER_KEY`**).
- **Portfolio rollup (internal):** `GET /internal/owners/portfolios-ranked?min_peers=2&limit=50`, `GET /internal/owners/peers-by-key?normalized_owner_key=…` (requires **`X-Internal-Key`** when configured).
- **Read stored brief:** `GET /parcels/{parcel_id}/outreach` (404 until a pipeline or recompute has written `owner_outreach_brief`).
- **Recompute without full pipeline:** `POST /parcels/{parcel_id}/outreach/recompute` with JSON body `fetch_sos`, `fetch_sos_detail`, `call_vendor` (booleans). Use this only for a parcel that meets the outreach target score floors. Async variant: `.../outreach/recompute/async` → poll `GET /internal/tasks/{task_id}`.
- **Pipeline-time HTTP (optional):** set `OUTREACH_PIPELINE_FETCH_SOS`, `OUTREACH_PIPELINE_FETCH_SOS_DETAIL`, and/or `OUTREACH_PIPELINE_CALL_VENDOR_WEBHOOK` to `true` so each `run_pipeline` builds the brief with the same integrations (use sparingly: rate limits and vendor cost).
- **Vendor webhook:** `OUTREACH_VENDOR_WEBHOOK_URL`, optional `OUTREACH_VENDOR_WEBHOOK_SECRET`, `OUTREACH_VENDOR_TIMEOUT_SEC`. **SOS client:** `OUTREACH_HTTP_USER_AGENT`, `OUTREACH_WA_SOS_TIMEOUT_SEC`.
- **Draft outbound messages (no sending):** `POST /parcels/{parcel_id}/outreach/message-draft` with JSON body `{ "channels": ["email","certified_mail"], "create_approval": true }`. This stores `parcels.outbound_message_drafts` and (optionally) creates a pending `ApprovalRequest(type=outbound_message)`.
- **Pipeline-time message draft approvals (optional):** set `OUTREACH_PIPELINE_CREATE_MESSAGE_APPROVAL=true` to automatically create an `outbound_message` approval during `run_pipeline`. Configure sender identity via `OUTREACH_SENDER_NAME`, `OUTREACH_SENDER_COMPANY`, `OUTREACH_SENDER_EMAIL`, `OUTREACH_SENDER_PHONE`.

## Deploy updates from your laptop

1. `git push` your changes (or ensure local tree matches what you want on the server).
2. `./scripts/sync-to-droplet.sh` (set `DROPLET`; optional `REMOTE_PATH` / `SSH_USER` — default remote path is `/opt/parking-acquisition-agents`; see [DROPLET_REPO_PATH.md](DROPLET_REPO_PATH.md)).
3. `./scripts/remote-rebuild.sh`

For **GHCR-only** stacks, push new images from CI first, then on the Droplet `docker compose -f deploy/docker-compose.production.ghcr.yml --env-file deploy/.env pull && ... up -d` (or use the full GHCR compose) — see [GHCR-DEPLOY.md](GHCR-DEPLOY.md).

## Secrets rotation

- Rotate **`INTERNAL_API_KEY`**: update `deploy/.env`, then `docker compose ... up -d` (API + worker pick up env on recreate).
- Rotate **Spaces keys** or **database password**: update DO resources, then `.env`, then recreate `api` and `worker` containers.

## Backups

- **Managed Postgres**: enable automated backups in the DigitalOcean control panel; test restore in a non-production cluster periodically.
- **Spaces**: versioning is optional; drafts are reproducible from DB metadata plus pipeline re-runs where acceptable.
