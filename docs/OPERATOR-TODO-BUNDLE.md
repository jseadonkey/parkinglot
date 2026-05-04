# Operator TODO bundle — batch these to minimize repeat effort

Use this as a **single checklist** when you sit down to finish Droplet work, instead of spreading the same tasks across many sessions. Detailed procedures stay in [OPERATIONS.md](OPERATIONS.md) and [PHASED-EXECUTION-PLAN-A-E.md](PHASED-EXECUTION-PLAN-A-E.md). **What is automated vs legally/vendor-external** is mapped in **[PROCESS-COVERAGE.md](PROCESS-COVERAGE.md)**. For **A–E setup verification** (env, Beat, Phase B file path, portfolio smoke), see **[A-E-SETUP-CHECKLIST.md](A-E-SETUP-CHECKLIST.md)**. For a **short post-break handoff** (DNS, `deploy/.env`, HTTPS smoke checks), see **[OPERATOR-NEXT-STEPS.md](OPERATOR-NEXT-STEPS.md)**.

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

**Phase B — zoning:** build the overlay with **`scripts/build_king_kent_zoning_overlay.py`** (see **`docs/zoning-sources-kent.md`**) or run the full **`scripts/run_phase_b_pipeline.sh`** (build → validate → **`execute-phase-b.sh`**). Stage output under **`data/`** so workers see **`/app/data/...`**. **`execute-phase-c.sh`** is a **smoke test**, not something that must run on a schedule.

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
- [ ] **Phase B** — set **`KENT_ZONING`** / **`KING_ZONING`** (Feature Layer URLs or paths), then **`./scripts/run_phase_b_pipeline.sh`**, or build manually with **`build_king_kent_zoning_overlay.py`** + **`execute-phase-b.sh`** — see **[PROCESS-COVERAGE.md](PROCESS-COVERAGE.md)**.
- [ ] **`./scripts/execute-phase-c.sh`** — portfolio smoke; optional **`PHASE_C_OWNER_KEY`** for peers-by-key.
- [ ] **`make readiness`** again — confirm gaps moved in the right direction.

Optional same session: **`make export-parcel-scores`** (Docker **`exec`** → **`parcel_scores_export.csv`**), or **`scripts/export_scored_parcels_csv.py`** / **`--publish-spaces`** — see OPERATIONS.

---

## True externals (counsel, vendors, infra — not automatable in code)

Do these when bandwidth allows — **not** every deploy (details: **[PROCESS-COVERAGE.md](PROCESS-COVERAGE.md)**):

- [ ] **Zoning rules YAML** (`data/zoning/wa/…` or `ZONING_RULES_PATH`) — ordinance-backed updates with **counsel** as jurisdictions change (repo holds placeholders).
- [ ] **Phase D inputs** (road centerlines, adjacency, richer demand surfaces) — **product/GIS agreement**; merge **`IS_CORNER`** / **`DIST_DEMAND_M`** via the same overlay pattern when data exists.
- [ ] **Owner vendor / SOS**: contracted vendor URLs + keys; rate-limit awareness for **`OUTREACH_*`** and pipeline SOS flags.
- [ ] **DNS / TLS / cloud account** — bind domains and secrets to your org (documented in **[GO-LIVE-WASHINGTON-DO.md](GO-LIVE-WASHINGTON-DO.md)**).

---

## Optional same-session extras

- [ ] Slack: bot in channel, **`SLACK_BOT_TOKEN`**, **`SLACK_DIGEST_CHANNEL_ID`**, **`make slack-droplet-check`** on the Droplet; optional **`make slack-digest-wait`** after fixing env; smoke **`POST /internal/slack/test-message`** — see [SLACK.md](SLACK.md).
- [ ] DigitalOcean Uptime: **`/ready`** URL — OPERATIONS.

---

## Doc map

| Topic | Where |
|--------|--------|
| Health, logs, CSV export, internal routes | [OPERATIONS.md](OPERATIONS.md) |
| Phase A–E meaning, exit criteria, **repo vs ops status** | [PHASED-EXECUTION-PLAN-A-E.md](PHASED-EXECUTION-PLAN-A-E.md) |
| Env var template | `deploy/env.production.example` |
| Phase runners | `scripts/execute-phase-a.sh`, **`run_phase_b_pipeline.sh`** / `execute-phase-b.sh`, `execute-phase-c.sh`, **`make readiness`** |
| Automation vs external responsibilities | **[PROCESS-COVERAGE.md](PROCESS-COVERAGE.md)** |

---

*Session checklist above is **repeatable ops** on live infra. **GIS joins and phased bursts** are **scripted in-repo**; **legal conclusions, vendor contracts, and county ToS** stay with your org — see **PROCESS-COVERAGE**.*
