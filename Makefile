.PHONY: help verify-sample export-readiness phase-a-run phase-b-run phase-c-run validate-phase-b-overlay local prod-up prod-down prod-pull prod-up-ghcr prod-pull-full prod-up-ghcr-full tf-init tf-plan slack-env-local droplet-sync droplet-rebuild droplet-rebuild-postgis gh-slack-notify-secret-help

help:
	@echo "Targets:"
	@echo "  make verify-sample      - venv + pytest sample GeoJSON trace (scores, enrichment, memo)"
	@echo "  make export-readiness   - print CSV column gap counts (needs DATABASE_URL)"
	@echo "  make phase-a-run        - Phase A: readiness + enqueue + identification backfill + demand refresh (needs DATABASE_URL; see scripts/execute-phase-a.sh)"
	@echo "  make phase-b-run        - Phase B: zoning overlay merge + readiness (needs DATABASE_URL + PHASE_B_OVERLAY_PATH; see scripts/execute-phase-b.sh)"
	@echo "  make validate-phase-b-overlay - dry-run overlay stats (needs PHASE_B_OVERLAY_PATH)"
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

verify-sample:
	@chmod +x scripts/verify-sample-trace.sh
	@./scripts/verify-sample-trace.sh

export-readiness:
	@test -n "$$DATABASE_URL" || (echo "export DATABASE_URL first"; exit 1)
	@chmod +x scripts/check_export_readiness.py
	@./scripts/check_export_readiness.py

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
