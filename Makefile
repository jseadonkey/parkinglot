.PHONY: help verify-sample api-ci openapi-export export-readiness readiness export-parcel-scores phase-a-run phase-b-run phase-b-pipeline phase-c-run validate-phase-b-overlay build-king-kent-zoning-overlay preflight-zoning slack-droplet-check slack-digest-wait poll-task process-coverage deploy-env-check render-deploy-env render-deploy-env-check ae-setup-check operator-console-snapshot operator-todos a-e-setup operator-console-help local prod-up prod-down prod-pull prod-up-ghcr prod-pull-full prod-up-ghcr-full tf-init tf-plan slack-env-local droplet-sync droplet-rebuild droplet-rebuild-postgis gh-slack-notify-secret-help

help:
	@echo "Targets:"
	@echo "  make verify-sample      - venv + pytest sample GeoJSON trace (scores, enrichment, memo)"
	@echo "  make api-ci             - venv + Ruff + pytest + OpenAPI export smoke (matches CI test-api)"
	@echo "  make openapi-export     - print OpenAPI JSON (needs .venv + deps like api-ci)"
	@echo "  make export-readiness   - print CSV column gap counts (needs DATABASE_URL)"
	@echo "  make readiness          - alias for export-readiness (Phase A–C gap summary)"
	@echo "  make export-parcel-scores - scored parcels CSV to ./parcel_scores_export.csv via docker compose api"
	@echo "  make phase-a-run        - Phase A: readiness + enqueue + identification backfill + demand refresh (needs DATABASE_URL; see scripts/execute-phase-a.sh)"
	@echo "  make phase-b-run        - Phase B: zoning overlay merge + readiness (needs DATABASE_URL + PHASE_B_OVERLAY_PATH; see scripts/execute-phase-b.sh)"
	@echo "  make validate-phase-b-overlay - dry-run overlay stats (needs PHASE_B_OVERLAY_PATH)"
	@echo "  make build-king-kent-zoning-overlay - build Phase B GeoJSON from KENT_ZONING + KING_ZONING URLs/paths (needs DATABASE_URL)"
	@echo "  make preflight-zoning    - inspect KENT_ZONING + KING_ZONING layers (field discovery)"
	@echo "  make phase-b-pipeline     - build + validate + merge Phase B (needs DATABASE_URL, KENT_ZONING, KING_ZONING, INTERNAL_API_KEY)"
	@echo "  make phase-c-run        - Phase C: readiness + portfolio internal APIs (needs DATABASE_URL; see scripts/execute-phase-c.sh)"
	@echo "  make local              - docker compose (dev: Postgres, Redis, MinIO, api, worker, UI)"
	@echo "  make slack-env-local    - merge SLACK_* into .env (needs SLACK_BOT_TOKEN + SLACK_DIGEST_CHANNEL_ID in env)"
	@echo "  make droplet-sync       - rsync repo to Droplet (needs DROPLET=ip, optional REMOTE_PATH / SSH_USER)"
	@echo "  make droplet-rebuild    - SSH: docker compose production up --build (needs DROPLET)"
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
	@echo "  make render-deploy-env  - merge deploy/env.production.example + deploy/secrets.env → deploy/.env"
	@echo "  make render-deploy-env-check - same + fail if required keys look empty"
	@echo "  make ae-setup-check     - verify deploy/.env keys for phased ops (+ optional /ready probe)"
	@echo "  make operator-todos - print path to bundled Droplet/GIS checklist (docs)"
	@echo "  make process-coverage    - print path to PROCESS-COVERAGE.md (automation vs externals)"
	@echo "  make slack-droplet-check - Slack diagnostics (beat/worker/env/logs); run on Droplet"
	@echo "  make slack-digest-wait   - POST digest-now + poll Celery (needs PUBLIC_API_URL, deploy/.env)"
	@echo "  make poll-task           - poll Celery task (export TASK_ID=… first)"
	@echo "  make a-e-setup    - print path to A–E setup checklist (docs)"
	@echo "  make operator-console-help - operator browser UI (/operator on UI_HOST)"
	@echo "  make operator-console-snapshot - same data as operator pages (troubleshooting)"

deploy-env-check:
	@python3 scripts/check_deploy_env_warnings.py

render-deploy-env:
	@python3 scripts/render_deploy_env.py

render-deploy-env-check:
	@python3 scripts/render_deploy_env.py --check

operator-todos:
	@echo "Bundled operator checklist (DNS, deploy, phases, backlog): docs/OPERATOR-TODO-BUNDLE.md"

process-coverage:
	@echo "Automation vs counsel/vendor/infra externals: docs/PROCESS-COVERAGE.md"

slack-droplet-check:
	@chmod +x scripts/slack_droplet_check.sh
	@./scripts/slack_droplet_check.sh

slack-digest-wait:
	@chmod +x scripts/slack_digest_now_wait.sh scripts/poll_internal_celery_task.sh
	@./scripts/slack_digest_now_wait.sh

poll-task:
	@test -n "$$TASK_ID" || (echo "export TASK_ID from POST …/internal/* response first"; exit 1)
	@chmod +x scripts/poll_internal_celery_task.sh
	@./scripts/poll_internal_celery_task.sh "$$TASK_ID"

a-e-setup:
	@echo "A–E configuration checklist (env, Beat, GIS, portfolio): docs/A-E-SETUP-CHECKLIST.md"

operator-console-help:
	@echo "Operator web UI (parcels, deals, approvals): docs/OPERATOR-CONSOLE.md"

operator-console-snapshot:
	@python3 scripts/operator_console_snapshot.py --probe-ui

ae-setup-check:
	@python3 scripts/check_ae_setup.py

verify-sample:
	@chmod +x scripts/verify-sample-trace.sh
	@./scripts/verify-sample-trace.sh

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

export-parcel-scores:
	@chmod +x scripts/export_parcel_scores_host.sh
	@./scripts/export_parcel_scores_host.sh

preflight-zoning:
	@chmod +x scripts/preflight_zoning_layers.sh
	@./scripts/preflight_zoning_layers.sh

phase-a-run:
	@test -n "$$DATABASE_URL" || (echo "export DATABASE_URL first"; exit 1)
	@chmod +x scripts/execute-phase-a.sh
	@./scripts/execute-phase-a.sh

phase-b-run:
	@test -n "$$DATABASE_URL" || (echo "export DATABASE_URL first"; exit 1)
	@test -n "$$PHASE_B_OVERLAY_PATH" || (echo "export PHASE_B_OVERLAY_PATH (absolute path to overlay GeoJSON)"; exit 1)
	@chmod +x scripts/execute-phase-b.sh
	@./scripts/execute-phase-b.sh

phase-b-pipeline:
	@test -n "$$DATABASE_URL" || (echo "export DATABASE_URL first"; exit 1)
	@test -n "$$INTERNAL_API_KEY" || (echo "export INTERNAL_API_KEY (merge POST uses /internal)"; exit 1)
	@test -n "$$KENT_ZONING" && test -n "$$KING_ZONING" || (echo "export KENT_ZONING and KING_ZONING"; exit 1)
	@chmod +x scripts/run_phase_b_pipeline.sh
	@./scripts/run_phase_b_pipeline.sh

build-king-kent-zoning-overlay:
	@test -n "$$DATABASE_URL" || (echo "export DATABASE_URL first"; exit 1)
	@test -n "$$KENT_ZONING" && test -n "$$KING_ZONING" || (echo "export KENT_ZONING and KING_ZONING (FeatureServer …/0 URLs or paths to GeoJSON)"; exit 1)
	@python3 scripts/build_king_kent_zoning_overlay.py -o "$${OVERLAY_OUT:-data/zoning/wa/king_kent_zoning_overlay.geojson}"

validate-phase-b-overlay:
	@test -n "$$PHASE_B_OVERLAY_PATH" || (echo "export PHASE_B_OVERLAY_PATH"; exit 1)
	@chmod +x scripts/validate_phase_b_overlay.py
	@./scripts/validate_phase_b_overlay.py "$$PHASE_B_OVERLAY_PATH"

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

droplet-sync:
	@test -n "$$DROPLET" || (echo "export DROPLET=<ipv4 or hostname>"; exit 1)
	./scripts/sync-to-droplet.sh

droplet-rebuild:
	@test -n "$$DROPLET" || (echo "export DROPLET=<ipv4 or hostname>"; exit 1)
	./scripts/remote-rebuild.sh

droplet-rebuild-postgis:
	@test -n "$$DROPLET" || (echo "export DROPLET=<ipv4 or hostname>"; exit 1)
	USE_LOCAL_POSTGIS=1 ./scripts/remote-rebuild.sh

gh-slack-notify-secret-help:
	@echo "Pipe INTERNAL_API_KEY value (key only) on stdin, e.g.:"
	@echo "  pbpaste | tr -d '\\n' | ./scripts/gh-set-slack-notify-internal-secret.sh"
	@echo "Requires: gh auth login, repo context (or GH_REPO=owner/name)."
