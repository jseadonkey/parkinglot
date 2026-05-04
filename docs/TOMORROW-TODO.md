# Tomorrow — open checklist (from recent sessions)

Parking stack @ `/opt/workspaces/parkinglot` on droplet `ubuntu-s-1vcpu-2gb-sfo3`.

---

## 1. Slack (digest skipped — env missing)

**Problem:** Worker logs show `slack_agent_digest SKIPPED` — `SLACK_BOT_TOKEN` / `SLACK_DIGEST_CHANNEL_ID` not in containers. Beat still runs every **20 minutes UTC**; tasks no-op until env is set.

**Verify keys in file:** `python3 scripts/check_ae_setup.py` → **Slack** line should be **OK** after you fix `.env`.

**Do:**

- [ ] Add to **`deploy/.env`** (real values):
  - `SLACK_BOT_TOKEN=xoxb-…`
  - `SLACK_DIGEST_CHANNEL_ID=C…` (channel ID from Slack; invite bot: `/invite @YourBot`)
- [ ] Restart:  
  `docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env up -d worker beat`
- [ ] Verify:  
  `set -a && source deploy/.env && set +a && chmod +x scripts/slack_droplet_check.sh && ./scripts/slack_droplet_check.sh`  
  → expect **`SLACK_BOT_TOKEN: set`** and **`slack_digest_configured: true`**
- [ ] Smoke (optional):  
  `chmod +x scripts/slack_digest_now_wait.sh && ./scripts/slack_digest_now_wait.sh`  
  (needs **`PUBLIC_API_URL`** in `deploy/.env`; use **`X-Internal-Key`** if **`INTERNAL_API_KEY`** is set)

**Refs:** [docs/SLACK.md](SLACK.md)

---

## 2. Phase B — zoning on parcels (CSV had empty `zoning_code`)

**Goal:** Fill zoning via overlay merge.

**Do:**

- [ ] Set **`KENT_ZONING`** and **`KING_ZONING`** (ArcGIS Feature Layer `…/FeatureServer/0` URLs or local GeoJSON paths) in **`deploy/.env`** or export for the session — see [docs/zoning-sources-kent.md](zoning-sources-kent.md)
- [ ] Discover zone columns (optional):  
  `python3 scripts/inspect_zoning_layer.py "$KENT_ZONING"` (and King) — tune **`--kent-zone-field`** / **`--king-zone-field`** if not defaults
- [ ] Run pipeline (needs **`DATABASE_URL`**, **`INTERNAL_API_KEY`** for merge HTTP):  
  `./scripts/run_phase_b_pipeline.sh`  
  or step-by-step: **`build_king_kent_zoning_overlay.py`** → **`validate_phase_b_overlay.py`** → **`execute-phase-b.sh`**
- [ ] **`make readiness`** or **`python3 scripts/check_export_readiness.py`** — **`parcels_missing_zoning_code`** should drop

**Refs:** [docs/PROCESS-COVERAGE.md](PROCESS-COVERAGE.md), `make process-coverage` (prints path)

---

## 3. Scores / pipelines (optional gaps)

If CSV still has blank **`score_entitlement`** / **`score_strategic`**:

- [ ] **`POST /internal/pipeline/enqueue-incomplete`** or rely on Celery Beat **`SCHEDULED_ENQUEUE_*`** in **`deploy/.env`**
- [ ] Confirm **`worker`** + **`redis`** healthy

---

## 4. Stakeholder CSV export (host file)

- [ ] **`chmod +x scripts/export_parcel_scores_host.sh`**  
  `./scripts/export_parcel_scores_host.sh`  
  → **`parcel_scores_export.csv`** in repo root (not container `/tmp`)
- [ ] Optional limit: **`EXPORT_LIMIT=10000`** prefix on same command

*(No **`make`** required on minimal Ubuntu — run scripts directly, or **`sudo apt install -y make`** if you want **`Makefile`** targets.)*

---

## 5. Quick command cheat-sheet (droplet)

```bash
cd /opt/workspaces/parkinglot
set -a && source deploy/.env && set +a

./scripts/slack_droplet_check.sh
./scripts/export_parcel_scores_host.sh
python3 scripts/check_export_readiness.py
```

---

*Generated as a working-memory handoff — adjust order to match your priority (Slack vs zoning vs exports).*
