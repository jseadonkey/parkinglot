# Operator TODO bundle — batch these to minimize repeat effort

Use this as a **single checklist** when you sit down to finish Droplet work, instead of spreading the same tasks across many sessions. Detailed procedures stay in [OPERATIONS.md](OPERATIONS.md) and [PHASED-EXECUTION-PLAN-A-E.md](PHASED-EXECUTION-PLAN-A-E.md). For **A–E setup verification** (env, Beat, Phase B file path, portfolio smoke), see **[A-E-SETUP-CHECKLIST.md](A-E-SETUP-CHECKLIST.md)**. For a **short post-break handoff** (DNS, `deploy/.env`, HTTPS smoke checks), see **[OPERATOR-NEXT-STEPS.md](OPERATOR-NEXT-STEPS.md)**. For a **phase-by-phase status** (what’s in-repo vs what’s on you), see **“Where we are — repo vs operations”** in the phased plan.

---

## Session 0 — Infra & DNS (fix once per environment or when TLS/DNS breaks)

- [ ] **`deploy/.env` is real**, not examples: `DATABASE_URL`, `INTERNAL_API_KEY`, Redis URLs, optional `STORAGE_*`, Slack tokens/channels if you use Slack.
- [ ] **DNS**: `API_HOST` / `PUBLIC_API_URL` hostnames resolve to the Droplet (**A/AAAA** records). Avoid placeholder domains (`api.parking.example.com` until updated).
- [ ] **TLS / Caddy**: `ACME_EMAIL` set; if ports aren’t 80/443, set `CADDY_PUBLISH_HTTP`, `CADDY_PUBLISH_HTTPS`, `PUBLIC_API_URL` (include **`:9443`** when relevant), `CORS_ALLOW_ORIGINS` with matching ports.
- [ ] **Firewall**: allow published HTTP/HTTPS ports (`ufw` etc.) — see OPERATIONS.

---

## Session 1 — Deploy the branch you care about

- [ ] Push/merge code (e.g. feature branch → main or deploy branch).
- [ ] On Droplet: **`git pull`** (or `./scripts/sync-to-droplet.sh` from laptop), then **`docker compose … pull && up -d`** / rebuild per [GHCR-DEPLOY.md](GHCR-DEPLOY.md) if applicable.
- [ ] Confirm **`GET /ready` → 200** using the **same URL path** your scripts will use:
  - From host: `curl -sS -o /dev/null -w "%{http_code}\n" "${PUBLIC_API_URL}/ready"`
  - If DNS isn’t ready yet: run checks **inside** the `api` container with `http://127.0.0.1:8000/ready` (see OPERATIONS — API is not on host `:8000` by default).

---

## Session 2 — One batched “phases” run (after parcels exist in Postgres)

**Automation (no manual scripts):** Celery Beat already **enqueues incomplete pipelines** on a schedule (`SCHEDULED_ENQUEUE_*` in `deploy/.env` — default every few hours). Optional Beat entries also run **identification** and **demand-distance** batch refreshes (`SCHEDULED_REFRESH_IDENTIFICATION_*`, `SCHEDULED_REFRESH_DEMAND_*` in `deploy/env.production.example`). Restart **worker + beat** after changing those variables.

**Phase B** still needs **your** zoning overlay GeoJSON staged on disk — merge can be scripted (cron) once the file path is stable. **`execute-phase-c.sh`** is a **smoke test**, not something that must run on a schedule.

Do **not** re-export secrets repeatedly — one shell block:

```bash
cd /opt/parking-acquisition-agents
set -a && source deploy/.env && set +a
export DATABASE_URL INTERNAL_API_KEY
```

Pick **one** way to reach the API for HTTP scripts:

| Situation | Set |
|-----------|-----|
| DNS works from Droplet host | `export PHASE_A_API_BASE="${PUBLIC_API_URL}"` (and use same idea for B/C `PHASE_*_API_BASE` if you override defaults) |
| DNS not ready / TLS issues | Run **`docker compose … exec api`** with `PHASE_*_API_BASE=http://127.0.0.1:8000` — see **`scripts/execute-phase-a.sh`**, **`execute-phase-b.sh`**, **`execute-phase-c.sh`** headers |

Then, in order:

- [ ] **`make readiness`** (alias for `make export-readiness`) — baseline gap counts (includes **`parcels_missing_owner_outreach_brief`**).
- [ ] **`./scripts/execute-phase-a.sh`** — enqueue + identification + demand (tune `PHASE_A_*`, optional `PHASE_A_JSON_DIR` for before/after JSON).
- [ ] **Phase B** (only when zoning overlay GeoJSON exists): stage file under repo **`data/`** so workers see **`/app/data/...`**, then **`./scripts/execute-phase-b.sh`** (`PHASE_B_OVERLAY_PATH`, optional `PHASE_B_OVERLAY_VALIDATE_PATH`).
- [ ] **`./scripts/execute-phase-c.sh`** — portfolio smoke; optional **`PHASE_C_OWNER_KEY`** for peers-by-key.
- [ ] **`make readiness`** again — confirm gaps moved in the right direction.

Optional same session: **`scripts/export_scored_parcels_csv.py`**, **`--publish-spaces`** — see OPERATIONS.

---

## Things only you / vendors / counsel supply (bundle decisions here)

Do these when you have GIS/legal/vendor bandwidth — **not** every deploy:

- [ ] **County zoning overlay** (spatial join → GeoJSON) — Phase B backlog; merge via **`execute-phase-b.sh`**.
- [ ] **Zoning rules YAML** (`data/zoning/wa/…` or `ZONING_RULES_PATH`) aligned with counsel as jurisdictions change.
- [ ] **Phase D inputs** (road centerlines, adjacency, richer demand surfaces) — when product/GIS agrees.
- [ ] **Owner vendor / SOS**: contracted vendor URLs + keys; rate-limit awareness for **`OUTREACH_*`** and pipeline SOS flags.

---

## Optional same-session extras

- [ ] Slack: bot in channel, **`SLACK_BOT_TOKEN`**, **`SLACK_DIGEST_CHANNEL_ID`**, smoke **`POST /internal/slack/test-message`** if desired.
- [ ] DigitalOcean Uptime: **`/ready`** URL — OPERATIONS.

---

## Doc map

| Topic | Where |
|--------|--------|
| Health, logs, CSV export, internal routes | [OPERATIONS.md](OPERATIONS.md) |
| Phase A–E meaning, exit criteria, **repo vs ops status** | [PHASED-EXECUTION-PLAN-A-E.md](PHASED-EXECUTION-PLAN-A-E.md) |
| City/county zoning inventory, value sources, jurisdiction QA feedback loop | [JURISDICTION-ZONING-COMPLETENESS-PLAN.md](JURISDICTION-ZONING-COMPLETENESS-PLAN.md) |
| Env var template | `deploy/env.production.example` |
| Phase runners | `scripts/execute-phase-a.sh`, `execute-phase-b.sh`, `execute-phase-c.sh`, **`make readiness`** |

---

*Everything above is “your side”; the assistant can keep shipping code and docs in-repo without needing live Droplet access.*
