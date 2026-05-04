# Process coverage — what the repo automates vs true externals

This is the single map from **historical “operator / GIS / your side” work** to **in-repo commands**. Use it when onboarding or prioritizing backlog.

---

## Fully automated in-repo (run on Droplet or CI worker)

| Former gap | Process |
|------------|---------|
| **Stakeholder CSV gaps** (scores, demand, centroids) | Celery Beat (`SCHEDULED_*` in `deploy/.env`) + **`scripts/execute-phase-a.sh`** bursts + **`make readiness`** / **`scripts/check_export_readiness.py`** |
| **Zoning overlay GeoJSON** (King/Kent pilot) | **`scripts/build_king_kent_zoning_overlay.py`** (`KENT_ZONING`, `KING_ZONING`, `DATABASE_URL`) → **`scripts/validate_phase_b_overlay.py`** → **`scripts/execute-phase-b.sh`**. **Field names:** **`scripts/inspect_zoning_layer.py`** on each layer URL. |
| **Zoning merge into parcels** | **`POST /internal/ingest/merge-geojson-attributes`** (worker task **`merge_parcel_attributes_geojson`**) |
| **Pipeline backlog** (entitlement/strategic) | **`POST /internal/pipeline/enqueue-incomplete`** + Beat schedule |
| **Export readiness metrics** | **`GET /internal/stats/export-readiness`**, operator UI overview, CLI **`check_export_readiness.py`** |
| **CSV export** | **`scripts/export_parcel_scores_host.sh`** or **`make export-parcel-scores`** (writes **`parcel_scores_export.csv`** via **`docker compose exec`**); or **`export_scored_parcels_csv.py -o -`** — avoid host **`/tmp`** inside the container without **`docker cp`**. |
| **Deploy hygiene** | **`make deploy-env-check`**, **`make ae-setup-check`**, **`scripts/check_deploy_env_warnings.py`** |
| **Operator routing / TLS smoke** | **`deploy/verify-operator-route-on-droplet.sh`** |
| **Lint parity with CI** | **`make api-ci`**, **`scripts/ci-api-local.sh`** |
| **Slack not posting** | **`make slack-droplet-check`**; **`scripts/slack_digest_now_wait.sh`** (manual digest + poll); **`scripts/poll_internal_celery_task.sh`** for any **`task_id`** |

---

## Scripted batch workflows (one session)

| Workflow | Entry point |
|----------|-------------|
| Phases A → B → C in order | **`docs/OPERATOR-TODO-BUNDLE.md`** Session 2 + env sourced from **`deploy/.env`** |
| Build overlay + validate + merge (Phase B only) | **`preflight_zoning_layers.sh`** / **`make preflight-zoning`** → **`scripts/run_phase_b_pipeline.sh`** or **`make phase-b-pipeline`** — needs **`KENT_ZONING`**, **`KING_ZONING`**, **`DATABASE_URL`**, **`INTERNAL_API_KEY`**, API reachable for merge POST |

---

## External by nature (cannot be coded away)

| Topic | Why it stays outside the repo |
|-------|-------------------------------|
| **Legal / zoning conclusions** | Ordinance interpretation, surface-parking **`kent_king_surface_parking_rules.yaml`** updates with counsel — we ship **structure**, not legal advice. |
| **Third-party contracts** | Vendor SOS/API keys, rate limits, permissible use — **`OWNER_VENDOR_LOOKUP_*`**, **`OUTREACH_*`**. |
| **County redistribution terms** | King County and others restrict bulk redistribution — automation **fetches** per their public APIs; compliance is **your** obligation to their terms. |
| **DNS, TLS certificates, firewall** | Infrastructure bindings to your domains and cloud account — docs guide; keys stay in **`deploy/.env`**. |
| **Road centerlines / hex demand surfaces** | Phase D enrichment inputs are **product/GIS agreements**; once delivered as GeoJSON or DB tables, the **merge** pattern is the same as Phase B (`IS_CORNER`, **`DIST_DEMAND_M`**, etc.). |

---

## Partially automated (data-dependent)

| Topic | Status |
|-------|--------|
| **Corner lot (`is_corner_lot`)** | Merge path exists (**`execute-phase-b.sh`** / overlay). **Deriving** corners from roads needs agreed inputs → Phase D backlog in **`docs/PHASED-EXECUTION-PLAN-A-E.md`**. |
| **WA SOS “clickwrap” links** | **`registry_lookup`** can emit **`manual_url_only`** — humans complete verification (by design). |
| **Multi-county rollout** | Repeat ingest + phases per county (`region.county_fips`); same scripts, new overlay URLs per jurisdiction when you add counties. |

---

## Quick commands (copy from repo root)

```bash
# Env (Droplet)
set -a && source deploy/.env && set +a
export DATABASE_URL INTERNAL_API_KEY

# Health
curl -sS -o /dev/null -w "%{http_code}\n" "${PUBLIC_API_URL}/ready"

# Gaps
make readiness

# Stakeholder CSV (host file — not container /tmp)
make export-parcel-scores
# Optional: EXPORT_LIMIT=10000 make export-parcel-scores

# Pick zone attribute columns (optional)
python3 scripts/inspect_zoning_layer.py "$KENT_ZONING"
python3 scripts/inspect_zoning_layer.py "$KING_ZONING"

# King/Kent zoning overlay + merge
make phase-b-pipeline
# or: ./scripts/run_phase_b_pipeline.sh
```

---

## Related docs

- **`docs/OPERATOR-TODO-BUNDLE.md`** — batched checklist  
- **`docs/PHASED-EXECUTION-PLAN-A-E.md`** — phases A–E  
- **`docs/zoning-sources-kent.md`** — Feature Layer URLs + automated overlay  
