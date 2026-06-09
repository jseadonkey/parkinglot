.PHONY: help verify-sample api-ci openapi-export export-readiness readiness phase-a-run phase-b-run phase-c-run validate-phase-b-overlay validate-jurisdictions address-coverage-report address-health-agent generate-wa-jurisdiction-registry zoning-governance build-baltimore-zoning-overlay baltimore-zoning-tiers baltimore-phase-b-local deploy-env-check ae-setup-check operator-todos a-e-setup operator-console-help local prod-up prod-down prod-pull prod-up-ghcr prod-pull-full prod-up-ghcr-full tf-init tf-plan slack-env-local lob-env-local droplet-sync droplet-rebuild droplet-rebuild-postgis gh-slack-notify-secret-help cursor-droplet run-crew-tests crew-audit crew-audit-droplet

help:
	@echo "Targets:"
	@echo "  make verify-sample      - venv + pytest sample GeoJSON trace (scores, enrichment, memo)"
	@echo "  make run-api-tests      - Ruff + pytest via scripts/run-api-tests.sh (Agent-friendly allowlist)"
	@echo "  make api-ci             - venv + Ruff + pytest + OpenAPI export smoke (matches CI test-api)"
	@echo "  make openapi-export     - print OpenAPI JSON (needs .venv + deps like api-ci)"
	@echo "  make export-readiness   - print CSV column gap counts (needs DATABASE_URL)"
	@echo "  make readiness          - alias for export-readiness (Phase A–C gap summary)"
	@echo "  make phase-a-run        - Phase A: readiness + enqueue + identification backfill + demand refresh (needs DATABASE_URL; see scripts/execute-phase-a.sh)"
	@echo "  make phase-b-run        - Phase B: zoning overlay merge + readiness (needs DATABASE_URL + PHASE_B_OVERLAY_PATH; see scripts/execute-phase-b.sh)"
	@echo "  make validate-phase-b-overlay - dry-run overlay stats (needs PHASE_B_OVERLAY_PATH)"
	@echo "  make validate-jurisdictions   - validate WA jurisdiction registry + address source catalog"
	@echo "  make address-coverage-report  - address source status (+ live WA gaps if DATABASE_URL set)"
	@echo "  make address-health-agent     - 12h-style review + source rotation (needs DATABASE_URL on Droplet)"
	@echo "  make generate-wa-jurisdiction-registry - refresh 102-row city/county registry CSV"
	@echo "  make zoning-governance  - validate jurisdiction zoning curation coverage for pilot/priority counties"
	@echo "  make build-baltimore-zoning-overlay - fetch parcels+zoning and build MD overlay GeoJSON (no DATABASE_URL)"
	@echo "  make baltimore-zoning-tiers   - print tier counts from local overlay GeoJSON"
	@echo "  make baltimore-phase-b-local  - fetch, build overlay, validate, summarize (no DATABASE_URL)"
	@echo "  make phase-c-run        - Phase C: readiness + portfolio internal APIs (needs DATABASE_URL; see scripts/execute-phase-c.sh)"
	@echo "  make local              - docker compose (dev: Postgres, Redis, MinIO, api, worker, UI)"
	@echo "  make slack-env-local    - merge SLACK_* into .env (needs SLACK_BOT_TOKEN + SLACK_DIGEST_CHANNEL_ID in env)"
	@echo "  make lob-env-local      - merge LOB_* + OUTREACH_SENDER_* into .env (see docs/LOB.md)"
	@echo "  make cursor-droplet     - open parkinglot-droplet.code-workspace (Remote SSH to Droplet)"
	@echo "  make droplet-sync       - rsync to parkinglot Droplet (uses deploy/droplet.target; no raw IP needed)"
	@echo "  make droplet-rebuild    - SSH rebuild production stack (uses deploy/droplet.target)"
	@echo "  make droplet-rebuild-postgis - same + on-droplet PostGIS addon (USE_LOCAL_POSTGIS=1)"
	@echo "  make gh-slack-notify-secret-help - print how to pipe INTERNAL_API_KEY into gh secret set"
	@echo "  make prod-up            - production compose build on Droplet (needs deploy/.env)"
	@echo "  make prod-up-ghcr       - production using GHCR API image (needs API_IMAGE in deploy/.env)"
	@echo "  make prod-pull          - pull GHCR images (API+worker compose)"
	@echo "  make prod-up-ghcr-full  - GHCR for API+worker+UI (needs API_IMAGE + APPROVAL_UI_IMAGE)"
	@echo "  make prod-pull-full     - pull all GHCR images (full compose)"
	@echo "  make prod-down          - stop production stack (default compose file)"
	@echo "  make tf-init       - terraform init -upgrade (infra/terraform)"
	@echo "  make tf-plan       - terraform plan (export TF_VAR_do_token and SPACES_* first)"
	@echo "  make deploy-env-check   - warn on placeholder deploy/.env (run on Droplet or laptop)"
	@echo "  make ae-setup-check     - verify deploy/.env keys for phased ops (+ optional /ready probe)"
	@echo "  make operator-todos - print path to bundled Droplet/GIS checklist (docs)"
	@echo "  make a-e-setup    - print path to A–E setup checklist (docs)"
	@echo "  make operator-console-help - operator browser UI (/operator on UI_HOST)"

deploy-env-check:
	@python3 scripts/check_deploy_env_warnings.py

operator-todos:
	@echo "Bundled operator checklist (DNS, deploy, phases, backlog): docs/OPERATOR-TODO-BUNDLE.md"

a-e-setup:
	@echo "A–E configuration checklist (env, Beat, GIS, portfolio): docs/A-E-SETUP-CHECKLIST.md"

operator-console-help:
	@echo "Operator web UI (parcels, deals, approvals): docs/OPERATOR-CONSOLE.md"
	@echo "Daily health agent: .github/workflows/operator-admin-agent.yml (08:00 UTC)"

operator-admin-agent-help:
	@echo "Operator admin agent — daily browser scan + metric stagnation + auto-fix on Droplet"
	@echo "  GitHub: Actions → Operator admin agent (daily)"
	@echo "  Scripts: scripts/operator-admin-agent/"
	@echo "  Snapshots: data/operator-agent/last-snapshot.json on Droplet"
	@bash scripts/droplet-operator-agent-install.sh

ae-setup-check:
	@python3 scripts/check_ae_setup.py

verify-sample:
	@chmod +x scripts/verify-sample-trace.sh
	@./scripts/verify-sample-trace.sh

run-api-tests:
	@chmod +x scripts/run-api-tests.sh
	@./scripts/run-api-tests.sh

api-ci:
	@chmod +x scripts/ci-api-local.sh
	@./scripts/ci-api-local.sh

openapi-export:
	@test -d .venv || (echo "Create .venv and run make api-ci once (or pip install workspace packages)"; exit 1)
	@. .venv/bin/activate && python3 scripts/export_openapi_json.py

export-readiness:
	@test -n "$$DATABASE_URL" || (echo "export DATABASE_URL first"; exit 1)
	@chmod +x scripts/check_export_readiness.py
	@./scripts/check_export_readiness.py

readiness: export-readiness

phase-a-run:
	@test -n "$$DATABASE_URL" || (echo "export DATABASE_URL first"; exit 1)
	@chmod +x scripts/execute-phase-a.sh
	@./scripts/execute-phase-a.sh

phase-b-run:
	@test -n "$$DATABASE_URL" || (echo "export DATABASE_URL first"; exit 1)
	@test -n "$$PHASE_B_OVERLAY_PATH" || (echo "export PHASE_B_OVERLAY_PATH (absolute path to overlay GeoJSON)"; exit 1)
	@chmod +x scripts/execute-phase-b.sh
	@./scripts/execute-phase-b.sh

validate-phase-b-overlay:
	@test -n "$$PHASE_B_OVERLAY_PATH" || (echo "export PHASE_B_OVERLAY_PATH"; exit 1)
	@chmod +x scripts/validate_phase_b_overlay.py
	@./scripts/validate_phase_b_overlay.py "$$PHASE_B_OVERLAY_PATH"

validate-jurisdictions:
	@python3 scripts/validate_jurisdictions.py

address-coverage-report:
	@python3 scripts/address_coverage_report.py

address-health-agent:
	@python3 scripts/address-health-agent/address_health_agent.py --json

generate-wa-jurisdiction-registry:
	@.venv/bin/python scripts/generate_wa_jurisdiction_registry.py

zoning-governance:
	@python3 scripts/check_zoning_governance.py

build-baltimore-zoning-overlay:
	@chmod +x scripts/fetch_baltimore_city_parcels.py scripts/fetch_baltimore_zoning_districts.py scripts/build_baltimore_zoning_overlay.py
	@python3 scripts/fetch_baltimore_city_parcels.py -o data/baltimore/baltimore_city_parcels.geojson
	@python3 scripts/fetch_baltimore_zoning_districts.py -o data/baltimore/baltimore_city_zoning_districts.geojson
	@python3 scripts/build_baltimore_zoning_overlay.py

baltimore-zoning-tiers:
	@python3 scripts/summarize_baltimore_zoning_tiers.py

baltimore-phase-b-local: build-baltimore-zoning-overlay
	@python3 scripts/validate_phase_b_overlay.py data/baltimore/baltimore_city_zoning_overlay.geojson
	@python3 scripts/summarize_baltimore_zoning_tiers.py

phase-c-run:
	@test -n "$$DATABASE_URL" || (echo "export DATABASE_URL first"; exit 1)
	@chmod +x scripts/execute-phase-c.sh
	@./scripts/execute-phase-c.sh

local:
	docker compose up --build

prod-up:
	docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env up -d --build

prod-down:
	docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env down

prod-pull:
	docker compose -f deploy/docker-compose.production.ghcr.yml --env-file deploy/.env pull

prod-up-ghcr:
	docker compose -f deploy/docker-compose.production.ghcr.yml --env-file deploy/.env up -d

prod-pull-full:
	docker compose -f deploy/docker-compose.production.ghcr-full.yml --env-file deploy/.env pull

prod-up-ghcr-full:
	docker compose -f deploy/docker-compose.production.ghcr-full.yml --env-file deploy/.env up -d

tf-init:
	cd infra/terraform && terraform init -upgrade

tf-plan:
	cd infra/terraform && terraform plan

slack-env-local:
	@test -n "$$SLACK_BOT_TOKEN" || (echo "export SLACK_BOT_TOKEN first"; exit 1)
	@test -n "$$SLACK_DIGEST_CHANNEL_ID" || (echo "export SLACK_DIGEST_CHANNEL_ID first"; exit 1)
	./scripts/set-slack-env-local.sh

lob-env-local:
	@test -n "$$LOB_API_KEY" || (echo "export LOB_API_KEY first"; exit 1)
	@test -n "$$LOB_FROM_ADDRESS_LINE1" || (echo "export LOB_FROM_ADDRESS_LINE1 first"; exit 1)
	@test -n "$$LOB_FROM_ADDRESS_CITY" || (echo "export LOB_FROM_ADDRESS_CITY first"; exit 1)
	@test -n "$$LOB_FROM_ADDRESS_STATE" || (echo "export LOB_FROM_ADDRESS_STATE first"; exit 1)
	@test -n "$$LOB_FROM_ADDRESS_ZIP" || (echo "export LOB_FROM_ADDRESS_ZIP first"; exit 1)
	./scripts/set-lob-env-local.sh

cursor-droplet:
	@./scripts/open-cursor-droplet.sh

droplet-sync:
	@./scripts/sync-to-droplet.sh

droplet-rebuild:
	@./scripts/remote-rebuild.sh

droplet-rebuild-postgis:
	@USE_LOCAL_POSTGIS=1 ./scripts/remote-rebuild.sh

gh-slack-notify-secret-help:
	@echo "Pipe INTERNAL_API_KEY value (key only) on stdin, e.g.:"
	@echo "  pbpaste | tr -d '\\n' | ./scripts/gh-set-slack-notify-internal-secret.sh"
	@echo "Requires: gh auth login, repo context (or GH_REPO=owner/name)."
