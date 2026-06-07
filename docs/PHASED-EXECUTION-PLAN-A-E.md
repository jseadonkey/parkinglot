# Phased execution plan (A–E)

This document breaks the **parcel CSV completeness**, **scoring**, **enrichment**, and **multi-county** work into five phases with **concrete tasks**, **commands/tools**, and **exit criteria**. It assumes the repo layout and internal APIs described in [OPERATIONS.md](OPERATIONS.md). For a **single batched operator checklist** (minimize repeat Droplet sessions), see [OPERATOR-TODO-BUNDLE.md](OPERATOR-TODO-BUNDLE.md). For a **compact “is A–E configured?”** verification list (env + compose + per-phase prerequisites), see **[A-E-SETUP-CHECKLIST.md](A-E-SETUP-CHECKLIST.md)**.

---

## Overview

| Phase | Theme | Primary outcome |
|-------|--------|-----------------|
| **A** | Scores + demand + readiness | CSV export has **identification, entitlement, strategic** and **distance_to_nearest_demand_m** wherever geometry + pilot POIs allow |
| **B** | Zoning + roll attributes | **`zoning_code`** and **`zoning_allows_surface_parking`** populated via overlay + rules YAML |
| **C** | Owner / portfolio / outreach | Recorded owner + contact hints + **same-owner rollup**; optional **vendor** hook with contracts |
| **D** | Advanced geometry | **Corner lot** (and stronger demand signals) from GIS / POI investments |
| **E** | Multi-region scale | Repeatable county/state rollout without one-off hacks |

### Where we are — repo vs operations (Phases A–E)

| Phase | Shipped in this repo (automatable) | Still on your side (batch when ready — see [OPERATOR-TODO-BUNDLE.md](OPERATOR-TODO-BUNDLE.md)) |
|-------|-------------------------------------|---------------------------------------------------------------------------------------------|
| **A** | `scripts/execute-phase-a.sh`, `check_export_readiness.py`, `GET /internal/stats/export-readiness`, enqueue + identification + demand-distance Celery tasks, OpenAPI response models, `make readiness` / `make phase-a-run` | Run against **live** Postgres/API on the Droplet (or laptop with `DATABASE_URL`); tune **`demand_generators`** in `pilot.yaml`; stakeholder CSV spot-check |
| **B** | `POST /internal/ingest/merge-geojson-attributes`, `scripts/execute-phase-b.sh`, `scripts/validate_phase_b_overlay.py`, `make validate-phase-b-overlay`, zoning rules YAML path (`ZONING_RULES_PATH`) | **Produce & stage zoning overlay GeoJSON** (spatial join); counsel review of surface-parking rules as jurisdictions change |
| **C** | `scripts/execute-phase-c.sh`, `make phase-c-run`, `GET /internal/owners/*`, outreach brief + memo paths in pipeline, **`parcels_missing_owner_outreach_brief`** in export-readiness | Run pipelines so briefs fill; optional **vendor / SOS** contracts + env; portfolio prioritization in your process |
| **D** | Baseline **`distance_to_nearest_demand_m`** (centroid→POI), **`is_corner_lot`** / **`DIST_DEMAND_M`** via ingest or merge overlay; strategic + identification YAML tuning | **GIS inputs** for defensible corner logic or richer demand (roads, adjacency, surfaces) — dedicated batch jobs **not** implemented until inputs exist (see Phase D backlog below) |
| **E** | Multi-county **`region.county_fips`** in `pilot.yaml`, ingest/WaTech routes, same phase scripts per county | Add each county to pilot + ingest + repeat **A→B→C** checklist; monitor **`export-readiness`** per rollout |

**Bottom line:** Phases **A–C** are **tool-complete** in code; **production proof** is running the scripts on real infra and closing **data** gaps (Phase **B** overlay is the largest recurring external dependency). Phases **D–E** are **partially** automated (D needs GIS investment; E is process + config repeating A–C).

---

## Phase A — Scores, demand distance, export readiness

### Goal

Stakeholder CSV columns **`score_identification`**, **`score_entitlement`**, **`score_strategic`**, **`distance_to_nearest_demand_m`**, **`centroid_lon`**, **`centroid_lat`** are populated **where the database and pilot config support them** (footprint + scores + generators).

### Prerequisites

- API + worker deployed; **`DATABASE_URL`** and **`INTERNAL_API_KEY`** (if used) available.
- `config/pilot.yaml` contains **`demand_generators`** you intend to use (replace illustrative POIs with real sites when possible).

### Tasks (execute in order)

**One-shot runner (Droplet or laptop with DB + API reachability):**  
[`scripts/execute-phase-a.sh`](../scripts/execute-phase-a.sh) — prints readiness **before** and **after**, calls **`enqueue-incomplete`** (repeatable rounds to drain \>500 backlog), **`refresh-identification-scores`** (optional poll), **`refresh-demand-distances`** (optional **poll** until Celery SUCCESS), optional CSV export + JSON snapshots. See script header for env vars (`DATABASE_URL`, `INTERNAL_API_KEY`, `PHASE_A_ENQUEUE_ROUNDS`, `PHASE_A_REFRESH_IDENTIFICATION`, `PHASE_A_IDENT_LIMIT`, `PHASE_A_POLL_IDENTIFICATION_TASK`, `PHASE_A_POLL_DEMAND_TASK`, `PHASE_A_JSON_DIR`, …).

Or run steps manually:

1. **Measure gaps**  
   - CLI: `python3 scripts/check_export_readiness.py` (requires `DATABASE_URL`).  
   - Or API: `GET /internal/stats/export-readiness` (same auth as other `/internal/*`).  
   **Done when:** You have counts for missing footprint, zoning, lot_sqft, demand distance, each score profile.

2. **Backfill Atlas + Beacon pair**  
   - `POST /internal/pipeline/enqueue-incomplete?limit=500` (repeat until `parcels_missing_entitlement_or_strategic` is acceptable).  
   - Celery Beat also runs incomplete enqueue on a schedule (see `SCHEDULED_ENQUEUE_*` in `deploy/env.production.example`).  
   **Done when:** `export-readiness` shows no (or acceptable) gap for entitlement/strategic for target parcels.

3. **Refresh demand distance from pilot POIs**  
   - `POST /internal/metrics/refresh-demand-distances?limit=2000`  
   - Optional filter: `county_fips=53033`.  
   **Done when:** `parcels_missing_distance_to_nearest_demand_m` drops (note: still null if **no generators** in `pilot.yaml` or **no footprint**).

4. **Identification score (Cartographer)**  
   - Normally written at **ingest**. If missing: **`POST /internal/metrics/refresh-identification-scores?limit=2000`** (Celery batch — no full re-ingest), or **re-ingest** / fix source GeoJSON.  
   **Done when:** `parcels_missing_score_identification` is acceptable.

5. **Export + publish**  
   - `python3 scripts/export_scored_parcels_csv.py -o …`  
   - Optional public URL: `--publish-spaces` with `STORAGE_*` env vars (see OPERATIONS).  
   - Or set **`PHASE_A_EXPORT_PATH`** (and optionally **`PHASE_A_PUBLISH_SPACES=1`**) when using **`execute-phase-a.sh`**.  
   **Done when:** Spot-check CSV: scores + centroids + demand for a sample county.

### Exit criteria (Phase A)

- `GET /internal/stats/export-readiness` (or CLI) shows **manageable** gaps only on columns deferred to Phase B (zoning) or D (corner).  
- Exported CSV matches stakeholder column list for **scores**, **demand**, **centroids**.

### Automated checks (Phase A)

- **`pytest services/api/tests/`** passes (includes **`test_openapi.py`** route/schema regression plus scoring paths).  
- **Sample trace:** `./scripts/verify-sample-trace.sh` (ingest + scores + pipeline shape).  
- **Bash:** `bash -n scripts/execute-phase-a.sh`.  
- **Local CI parity:** `make api-ci` or `./scripts/ci-api-local.sh` (same Ruff + pytest + OpenAPI JSON export smoke as GitHub Actions `test-api`).  
- **With live DB + API** (Droplet or port-forward): `DATABASE_URL=… INTERNAL_API_KEY=… ./scripts/execute-phase-a.sh` — before/after `check_export_readiness.py` should show `parcels_missing_score_*` and demand gaps moving in the right direction (worker time may require re-run or longer `PHASE_A_WAIT_SEC`).

### References (code / docs)

- `scripts/check_export_readiness.py`, `services/api/app/export_readiness.py`  
- `POST /internal/pipeline/enqueue-incomplete`, `POST /internal/metrics/refresh-demand-distances`  
- `docs/OPERATIONS.md` (CSV + internal routes)

---

## Phase B — Zoning and surface-parking flags

### Goal

Populate **`zoning_code`** and **`zoning_allows_surface_parking`** (and optional props such as **`IS_CORNER`**, **`DIST_DEMAND_M`** if present on overlay) for parcels where the **county does not ship zoning on the parcel polygon layer** (typical for WaTech-only ingest).

### Prerequisites

- Jurisdiction’s **zoning GIS** (or assessor export) you can **spatially join** to parcel polygons outside this app (QGIS, ArcGIS, Python, county workflow).  
- `data/zoning/wa/kent_king_surface_parking_rules.yaml` (or path from **`ZONING_RULES_PATH`**) curated for **`ZONING`** + **`ZONING_JURISDICTION`** pairs you emit.

### Tasks (execute in order)

1. **Produce overlay GeoJSON**  
   - Same parcel identity as production: **`COUNTY_FIPS`** + **`APN`** / **`PIN`** / `PARCEL_ID_NR` (must match ingest aliases — see `geojson_loader`).  
   - Properties to set at minimum: **`ZONING`** (label), **`ZONING_JURISDICTION`** (e.g. `kent_city`, `king_unincorporated` per your YAML).  
   - Optional: **`IS_CORNER`**, **`DIST_DEMAND_M`** if computed in GIS.

2. **Stage file on server**  
   - Path visible inside **worker** container (e.g. repo `data/` → **`/app/data/...`** in containers).  
   - Quick lint (same loader as merge): **`python3 scripts/validate_phase_b_overlay.py /path/on/host.geojson`** — or rely on **`scripts/execute-phase-b.sh`** (runs validation before POST). If the merge POST uses **`/app/data/...`** but you validate from the host, set **`PHASE_B_OVERLAY_VALIDATE_PATH`** to the host file path.

3. **Merge attributes (no footprint replacement)**  
   - `POST /internal/ingest/merge-geojson-attributes` with JSON body, e.g.:  
     `{"path":"/abs/path/overlay.geojson","refresh_pipeline":true,"max_pipeline":200}`  
   - Or Droplet/laptop runner: [**`scripts/execute-phase-b.sh`**](../scripts/execute-phase-b.sh) — prints readiness before/after, POSTs merge with safe JSON encoding (`PHASE_B_OVERLAY_PATH`, optional poll).  
   - This updates existing parcels, merges **`raw_properties`**, refreshes **identification** scores, and enqueues **`run_pipeline`** up to **`max_pipeline`**.

4. **Verify rules coverage**  
   - If `zoning_allows_surface_parking` is wrong, fix **`kent_king_surface_parking_rules.yaml`** (or jurisdiction file) and remerge or re-ingest.

5. **Re-run Phase A checks**  
   - `check_export_readiness.py` → zoning gap counts should fall.

### Exit criteria (Phase B)

- `export-readiness`: **`parcels_missing_zoning_code`** acceptable for your pilot counties.  
- Spot parcels: zoning string + surface-parking flag align with counsel / zoning memo.

### References

- `services/ingestion/parking_ingestion/geojson_loader.py` (property aliases)  
- `services/ingestion/parking_ingestion/zoning_rules.py`  
- `POST /internal/ingest/merge-geojson-attributes` — `services/api/app/tasks.py` (`merge_parcel_attributes_geojson`)  
- `docs/zoning-sources-kent.md`, `data/zoning/wa/README.md`

### Backlog — merge a **real** zoning overlay (tracked deliverable)

The codebase includes merge endpoints, **`scripts/execute-phase-b.sh`**, and **`scripts/validate_phase_b_overlay.py`**. What is **not** done until ops/GIS completes it is the **authoritative overlay GeoJSON per pilot county**: spatial join parcel polygons to jurisdiction zoning GIS (outside this repo), properties aligned with **`geojson_loader`** aliases and **`kent_king_surface_parking_rules.yaml`**, staged on the Droplet under **`data/`** (worker path **`/app/data/...`**), then merge + verify **`parcels_missing_zoning_code`** drops and counsel spot-checks **`zoning_allows_surface_parking`**. Treat **“implement Phase B for production parcels”** as **shipping that file + running merge**, not only enabling the automation.

---

## Phase C — Owner intelligence, portfolio, compliance

### Goal

Operators can see **recorded owner**, **contact hints from roll**, **multi-parcel rollup** by normalized owner key, **registry (SOS) links** for entities, optional **vendor** enrichment — without treating scraped web data as verified contact permission.

### Prerequisites

- Assessor / ingest includes **`OWNER_NAME`** (and mail/phone/email fields where available) in **`raw_properties`** (`geojson_loader` / WaTech props).  
- For vendor use: contracted provider, **`OWNER_VENDOR_LOOKUP_*`** in `deploy/.env`, counsel-approved permissible purpose.

### Tasks (execute in order)

1. **Validate ingest fields**  
   - Confirm county export maps into **`raw_properties`** with keys the outreach brief reads (`MAIL_*`, `OWNER_PHONE`, etc.).  
   **Done when:** Deal memo / outreach brief shows mailing/phone/email when the county provides them.

2. **Run pipeline for enriched parcels**  
   - Owner candidates + **`owner_outreach_brief`** are written in **`run_pipeline`** (`services/api/app/tasks.py`).  
   - Ensure pipelines have run for parcels you care about (Phase A enqueue).
   - Street / situs addresses are **deal-candidate enrichment only**. Backfill them for parcels that score well or look vacant/suitable; do not treat missing addresses on low-score parcels as city/county incompleteness.

3. **Portfolio rollup**  
   - `GET /internal/owners/peers-by-key?normalized_owner_key=53:ACME`  
   - `GET /internal/owners/portfolios-ranked?min_peers=2`  
   **Done when:** You can list **other qualified parcels** sharing an owner key (understanding false merges — same name ≠ same person).

4. **WA SOS / other registries**  
   - Brief includes **`registry_lookup`** with **`manual_url_only`** for WA entities (CCFS). Humans complete verification.

5. **Optional vendor webhook**  
   - Set **`OWNER_VENDOR_LOOKUP_ENABLED`**, **`OWNER_VENDOR_LOOKUP_URL`**, **`OWNER_VENDOR_LOOKUP_API_KEY`** (see `deploy/docker-compose.production.yml` / worker env).  
   **Done when:** **`vendor_lookup`** appears on brief with provider outcome; errors surfaced in memo.

6. **Smoke readiness + portfolio APIs**  
   - **`scripts/execute-phase-c.sh`** — prints **`parcels_missing_owner_outreach_brief`** (via **`check_export_readiness.py`**), **`GET /internal/owners/portfolios-ranked`**, optional **`GET /internal/owners/peers-by-key`** when **`PHASE_C_OWNER_KEY`** is set (`make phase-c-run`). Use after pipelines have run for parcels you care about.
   - Interpret remaining owner/address gaps as candidate-only work; broad market coverage does not require street addresses for every APN.

### Exit criteria (Phase C)

- Owner lines + outreach sections appear on deal memos for pipeline-completed parcels.  
- Portfolio endpoints usable for **multi-lot** prioritization.  
- No automated cold outreach — counsel workflow unchanged.

### References

- `services/enrichment/parking_enrichment/owner_outreach_agent.py`  
- `services/enrichment/parking_enrichment/registry_lookup.py`, `vendor_lookup_client.py`  
- `services/api/app/owner_portfolio.py`, `services/api/app/memo_render.py`

---

## Phase D — Corner lot + stronger demand (geometry-heavy)

### Goal

Improve **`is_corner_lot`** beyond roll flags and strengthen **`distance_to_nearest_demand_m`** / strategic signal using **real world geometry and demand data**.

### Prerequisites

- **Road centerlines** or **parcel-adjacency** inputs agreed with GIS.  
- Optional: POI database, traffic counts, or hex/grid demand surfaces (product decision).

### Tasks (conceptual — implement when data exists)

1. **Corner lot**  
   - Define rule (e.g. parcel touches **two non-collinear road frontages**).  
   - Build enrichment job (batch or Celery) that writes **`IS_CORNER`** into properties or updates **`Parcel.is_corner_lot`** via internal merge pattern.  
   - Re-run identification + pipeline for affected parcels.

2. **Demand signal beyond centroid→POI**  
   - Replace single-buffer logic with agreed metric (drive time, weighted POIs, hex demand surface).  
   - Implement in **`parcel_metrics`** / ingest path; document pilot config schema changes.

3. **Validate**  
   - Sample ground-truth parcels; tune weights in **`pilot_strategic.yaml`** / identification as needed.

### Exit criteria (Phase D)

- `is_corner_lot` defensible against manual QA on a pilot set.  
- Strategic scores correlate better with “visibility / demand” intent (team sign-off).

### References

- `services/ingestion/parking_ingestion/parcel_metrics.py`  
- `services/scoring/parking_scoring/engine.py`  
- `config/pilot_strategic.yaml`, `config/pilot_identification.yaml`

### Backlog — corner lot + richer demand (implement when GIS data exists)

Stronger **`is_corner_lot`** and demand signals require **inputs agreed outside this repo** (road centerlines, parcel–road topology, optional drive-time / hex demand surfaces). Until those exist, Phase D progress is **tuning existing YAML weights** and **`parcel_metrics`** centroid→POI behavior already shipped. Tracked deliverables later: a **batch or Celery job** that writes corner flags or enriched demand fields (via merge GeoJSON or DB update), then **identification / pipeline** refresh for affected parcels.

---

## Phase E — Multi-city / multi-county / multi-state scale

### Goal

Repeat Phases A–D for **new counties** and eventually **new states** without forked code paths.

### Prerequisites

- **`config/pilot.yaml`** `region.county_fips` includes all active counties.  
- Per-county **overlay GeoJSON** (Phase B) or standardized ingest contract.  
- Per-state **registry** strategy (WA SOS today; others = `skipped_not_wa` until plug-ins exist).

### Tasks (execute in order)

1. **Add county to pilot region**  
   - Update YAML; redeploy or reload config as you do today.

2. **Ingest or WaTech fetch**  
   - `POST /internal/ingest/watech-county` or GeoJSON server path upload.

3. **Zoning overlay per county**  
   - Phase B merge for that county’s FIPS.

4. **Normalize owner keys**  
   - `scoped_owner_key` uses **state FIPS prefix** from `county_fips`; document cross-state limitations.

5. **Score backfill at scale**  
   - `enqueue-incomplete`, Beat schedules, optional raised **`limit`** during bulk catch-up.

6. **Monitoring**  
   - `export-readiness` + **`GET /internal/stats/scoring-summary`** per release train.

### Exit criteria (Phase E)

- New county reaches **same checklist** as pilot: readiness stats green enough → CSV export → stakeholder review.

### References

- `config/pilot.yaml`, `deploy/env.production.example`  
- `services/enrichment/parking_enrichment/owner_normalize.py`

### Repeat per county (same automation)

After **`region.county_fips`** and ingest for a new county, run the same operational scripts as the pilot: **`make readiness`** ([`check_export_readiness.py`](../scripts/check_export_readiness.py)), **[`scripts/execute-phase-a.sh`](../scripts/execute-phase-a.sh)**, **[`scripts/execute-phase-b.sh`](../scripts/execute-phase-b.sh)** when a zoning overlay exists, **[`scripts/execute-phase-c.sh`](../scripts/execute-phase-c.sh)** for portfolio smoke — then **`export-readiness`** until gaps are acceptable.

---

## Quick reference — HTTP endpoints (internal auth)

| Purpose | Method & path |
|--------|----------------|
| Export readiness gaps | `GET /internal/stats/export-readiness` |
| Enqueue missing entitlement **or** strategic | `POST /internal/pipeline/enqueue-incomplete` |
| Enqueue missing entitlement only | `POST /internal/pipeline/enqueue-unscored` |
| Refresh demand distances | `POST /internal/metrics/refresh-demand-distances` |
| Backfill identification scores | `POST /internal/metrics/refresh-identification-scores` |
| Merge zoning / overlay attributes | `POST /internal/ingest/merge-geojson-attributes` |
| Owner peers by key | `GET /internal/owners/peers-by-key` |
| Rank portfolios | `GET /internal/owners/portfolios-ranked` |
| Celery task status | `GET /internal/tasks/{task_id}` |

**Shell helpers:** Phase A — [`scripts/execute-phase-a.sh`](../scripts/execute-phase-a.sh); Phase B overlay — [`scripts/execute-phase-b.sh`](../scripts/execute-phase-b.sh); Phase B dry-run — [`scripts/validate_phase_b_overlay.py`](../scripts/validate_phase_b_overlay.py) (`make validate-phase-b-overlay`); Phase C — [`scripts/execute-phase-c.sh`](../scripts/execute-phase-c.sh) (`make phase-c-run`).

---

## Suggested ownership

| Phase | Typical owners |
|-------|----------------|
| A | Backend ops + PM (CSV consumer) |
| B | GIS / data vendor + engineer (merge + rules YAML) |
| C | Legal + outreach lead + engineer (vendor integration) |
| D | GIS + data science + engineer |
| E | Program lead + county rollout owner |

---

*Last updated to match internal routes and scripts in the same repo revision as this file.*

**Outstanding (note for roadmap):** Phase B **backlog** — production zoning overlay merge per county once GIS delivers the file. Phase D **backlog** — corner/demand enrichment jobs once road/adjacency or demand-surface inputs exist.
