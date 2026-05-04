# A–E setup checklist (repo + deploy)

Use this to confirm **each phase is configured**, not necessarily “all data gaps closed.” Data gaps are tracked separately via **`GET /internal/stats/export-readiness`** / **`scripts/check_export_readiness.py`**.

**Machine check (Droplet / laptop with `deploy/.env`):**

```bash
make ae-setup-check
# optional live HTTPS check (skips TLS verify — matches internal Caddy):
python3 scripts/check_ae_setup.py --probe
```

**Related:** [PHASED-EXECUTION-PLAN-A-E.md](PHASED-EXECUTION-PLAN-A-E.md), [OPERATOR-TODO-BUNDLE.md](OPERATOR-TODO-BUNDLE.md), **[PROCESS-COVERAGE.md](PROCESS-COVERAGE.md)** (automation vs externals), `deploy/env.production.example`.

---

## Shared (all phases)

- [ ] **`deploy/.env`** exists on the Droplet (never committed): **`DATABASE_URL`**, **`INTERNAL_API_KEY`**, **`REDIS_URL`**, **`CELERY_*`**, **`PUBLIC_API_URL`**, **`CORS_ALLOW_ORIGINS`**, **`STORAGE_*`** (contract drafts / CSV publish).
- [ ] **`docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env ps`** — **`api`**, **`worker`**, **`beat`**, **`redis`**, **`caddy`** running.
- [ ] **`curl`** (or browser) — **`GET ${PUBLIC_API_URL}/ready`** → **200**.
- [ ] Config mounted in containers: **`config/pilot.yaml`**, **`pilot_strategic.yaml`**, **`pilot_identification.yaml`** (compose mounts **`../config`**).

---

## Phase A — Scores, demand distance, export readiness

**Shipped:** enqueue incomplete pipelines, identification/demand batch tasks, **`scripts/execute-phase-a.sh`**, Beat schedules.

- [ ] **Backlog drain (automatic):** **`SCHEDULED_ENQUEUE_UNSCORED_ENABLED`** (default on), **`SCHEDULED_ENQUEUE_UNSCORED_LIMIT`**, **`SCHEDULED_ENQUEUE_UNSCORED_CRONTAB_*`** in **`deploy/.env`** → restart **worker + beat** after changes.
- [ ] **Optional — identification + demand batches on a timer:** **`SCHEDULED_REFRESH_IDENTIFICATION_ENABLED`**, **`SCHEDULED_REFRESH_DEMAND_ENABLED`** (+ limits/cron in **`deploy/env.production.example`**) → restart **worker + beat**.
- [ ] **`config/pilot.yaml`** — **`demand_generators`** populated for your pilot (not placeholder-only if you rely on demand distance).
- [ ] **Verify:** **`python3 scripts/check_export_readiness.py`** (needs **`DATABASE_URL`**) or **`GET /internal/stats/export-readiness`** with **`X-Internal-Key`**.
- [ ] **Optional manual burst:** **`./scripts/execute-phase-a.sh`** with **`PHASE_A_API_BASE="${PUBLIC_API_URL}"`** (HTTPS internal TLS is handled in-script).

---

## Phase B — Zoning overlay + surface-parking rules

**Shipped:** merge endpoint, **`scripts/execute-phase-b.sh`**, **`scripts/validate_phase_b_overlay.py`**, **`data/zoning/wa/`** rules YAML.

- [ ] **Rules file:** **`ZONING_RULES_PATH`** in **`deploy/.env`** if not using default repo rules under **`data/zoning/wa/`**.
- [ ] **Overlay artifact (your GIS):** county overlay **GeoJSON** staged under repo **`data/`** so the worker sees **`/app/data/...`** (same bind mount as **`deploy/docker-compose.production.yml`**).
- [ ] **Dry-run:** **`python3 scripts/validate_phase_b_overlay.py /path/to/overlay.geojson`** on the host copy.
- [ ] **Merge:** **`PHASE_B_OVERLAY_PATH=/app/data/...`** **`./scripts/execute-phase-b.sh`** (set **`PHASE_B_API_BASE`** like Phase A).  
  **Automation:** optional **cron** after your GIS job writes the file to a fixed path.
- [ ] **Verify:** **`parcels_missing_zoning_code`** drops in export-readiness.

---

## Phase C — Owner / portfolio / outreach brief

**Shipped:** pipeline writes **`owner_outreach_brief`**, **`GET /internal/owners/*`**, **`scripts/execute-phase-c.sh`**.

- [ ] **Ingest:** parcel **`OWNER_NAME`** / mail fields present in **`raw_properties`** for counties you care about (assessor / WaTech mapping).
- [ ] **Pipelines:** Phase A enqueue / Beat has run so **`run_pipeline`** completed for target parcels (brief is pipeline-written).
- [ ] **Optional vendor:** **`OWNER_VENDOR_LOOKUP_ENABLED`**, **`OWNER_VENDOR_LOOKUP_URL`**, **`OWNER_VENDOR_LOOKUP_API_KEY`** in **`deploy/.env`** (worker receives them — see compose **`x-worker-beat-env`**).
- [ ] **Smoke:** **`./scripts/execute-phase-c.sh`** with **`PHASE_C_API_BASE="${PUBLIC_API_URL}"`**; optional **`PHASE_C_OWNER_KEY`** for peers-by-key.

---

## Phase D — Corner lot + richer demand (geometry-heavy)

**Shipped:** centroid→POI demand distance, YAML tuning; **stronger corner/demand** needs GIS inputs.

- [ ] **Now (no extra GIS):** tune **`config/pilot_strategic.yaml`**, **`pilot_identification.yaml`**; use **`refresh-demand-distances`** / Beat **`SCHEDULED_REFRESH_DEMAND_*`** as needed.
- [ ] **Later (when data exists):** road centerlines / adjacency / hex surfaces agreed with GIS → batch jobs or merge overlays (see phased plan **Phase D backlog**). Not a single env toggle.

---

## Phase E — Multi-county / scale

**Shipped:** **`region.county_fips`** in **`config/pilot.yaml`**, ingest routes, same phase scripts per county.

- [ ] **`config/pilot.yaml`** — **`region.county_fips`** lists every pilot county.
- [ ] **Per county:** ingest (**GeoJSON**, **`/internal/ingest/geojson-server-path`**, or WaTech county route per docs) → **Phase B overlay** per county → Phase A-style backfill (**Beat** + optional **`execute-phase-a.sh`**).
- [ ] **Monitoring:** **`export-readiness`**, **`GET /internal/stats/scoring-summary`** after bulk changes.

---

## One-line “are we wired?” summary

| Phase | Mostly automatic once env is set? | You still supply |
|-------|-------------------------------------|------------------|
| **A** | Yes — Beat + optional refresh flags | Pilot YAML POIs; occasional manual **`execute-phase-a`** bursts |
| **B** | Merge runs when **file exists** | **Zoning overlay GeoJSON** + counsel on rules YAML |
| **C** | Briefs fill when **pipelines** run | Clean assessor fields; optional **vendor** contract |
| **D** | Partial — YAML + existing metrics | **GIS inputs** for stronger corner/demand |
| **E** | Repeat **A→B→C** pattern | County list + ingest + overlays per jurisdiction |

When this checklist is green for **A + deploy**, you are **set up** for ongoing operations; **B–E** add items as counties and GIS/vendor scope expand.
