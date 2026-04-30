.PHONY: help local prod-up prod-down prod-pull prod-up-ghcr prod-pull-full prod-up-ghcr-full tf-init tf-plan slack-env-local

help:
	@echo "Targets:"
	@echo "  make local              - docker compose (dev: Postgres, Redis, MinIO, api, worker, UI)"
	@echo "  make slack-env-local    - merge SLACK_* into .env (needs SLACK_BOT_TOKEN + SLACK_DIGEST_CHANNEL_ID in env)"
	@echo "  make prod-up            - production compose build on Droplet (needs deploy/.env)"
	@echo "  make prod-up-ghcr       - production using GHCR API image (needs API_IMAGE in deploy/.env)"
	@echo "  make prod-pull          - pull GHCR images (API+worker compose)"
	@echo "  make prod-up-ghcr-full  - GHCR for API+worker+UI (needs API_IMAGE + APPROVAL_UI_IMAGE)"
	@echo "  make prod-pull-full     - pull all GHCR images (full compose)"
	@echo "  make prod-down          - stop production stack (default compose file)"
	@echo "  make tf-init       - terraform init -upgrade (infra/terraform)"
	@echo "  make tf-plan       - terraform plan (export TF_VAR_do_token and SPACES_* first)"

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
