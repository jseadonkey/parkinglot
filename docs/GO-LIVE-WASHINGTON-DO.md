# Go live: Washington pilot on DigitalOcean

This runbook gets the stack off your laptop: **Managed Postgres**, **Spaces**, **Droplet** running **API + Celery worker + approval UI + Redis + Caddy (TLS)** 24/7.

## 0. Prerequisites

- DigitalOcean account, API token (`read` + `write`).
- Domain you control (for HTTPS). Two hostnames:
  - **UI**: e.g. `parking.example.com`
  - **API**: e.g. `api.parking.example.com`
- SSH key added in DO (for Droplet access). Restrict SSH in Terraform from your IP if possible (`admin_ssh_source_cidrs`).

Closest DO region to Washington is **`sfo3`** (no Seattle datacenter). Use **the same region** for Droplet, Managed Postgres, and Spaces.

## 1. Provision infrastructure (Terraform)

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit: spaces_bucket_name (globally unique), droplet_ssh_keys, optional admin_ssh_source_cidrs
export TF_VAR_do_token="dop_v1_..."
terraform init
terraform apply
```

After apply:

1. **Managed Postgres — enable PostGIS**  
   In DO control panel: open the database cluster → **Query** (or psql) as admin and run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS postgis;
   ```
2. **Grant the app user on `parking_app` (one-time)**  
   In the DO SQL console, connect to database **`parking_app`** as admin (often `doadmin`), then run:
   ```sql
   GRANT ALL ON SCHEMA public TO parking_api;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO parking_api;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO parking_api;
   ```
   Also run `GRANT CONNECT ON DATABASE parking_app TO parking_api;` from a session attached to `defaultdb` if the user cannot connect yet. If migrations fail with “permission denied”, re-check these grants.

3. **Spaces**  
   Terraform creates the bucket and a **scoped runtime key** (`digitalocean_spaces_key`). Export `SPACES_ACCESS_KEY_ID` / `SPACES_SECRET_ACCESS_KEY` before `terraform apply` so Terraform can manage Spaces (see `infra/terraform/README.md`). After apply, set `deploy/.env` from:
   `terraform output -raw spaces_runtime_access_key` and `terraform output -raw spaces_runtime_secret_key`.

4. **DNS**  
   Point **A** (and **AAAA** if you use IPv6) for `UI_HOST` and `API_HOST` to the Droplet **public IPv4** from Terraform output.

5. **Connection string**  
   After `terraform apply`, run `terraform output -raw database_url_sqlalchemy` (sensitive) and paste into `deploy/.env` as `DATABASE_URL`, or build it from the DO UI for user `parking_api`, database `parking_app`, with **`sslmode=require`**.

## 2. Terraform outputs (sanity check)

```bash
terraform output droplet_ipv4
terraform output -raw database_url_sqlalchemy
terraform output spaces_bucket_name
terraform output spaces_bucket_endpoint
terraform output -raw spaces_runtime_access_key
terraform output -raw spaces_runtime_secret_key
```

## 3. Bootstrap the Droplet

SSH as root (or sudo user):

```bash
apt-get update -y
apt-get install -y git rsync
# Docker already installed via cloud-init; verify:
docker version
```

Clone or rsync this repository to `/opt/parking-acquisition-agents` (or your path). Example:

```bash
mkdir -p /opt && cd /opt
git clone <YOUR_REPO_URL> parking-acquisition-agents
cd parking-acquisition-agents
```

## 4. Configure production env

```bash
cd deploy
cp env.production.example .env
nano .env   # fill DATABASE_URL, Spaces keys, UI_HOST, API_HOST, PUBLIC_API_URL
chmod 600 .env
```

Optional: with a **`DO_TOKEN`** GitHub Action secret, run the read-only workflows under **Actions** to print Droplet public IPs, Managed Postgres connection hints, and Spaces key metadata (see [deploy/README.md](../deploy/README.md#digitalocean-read-only-helpers-github-actions)).

`PUBLIC_API_URL` must be the **public HTTPS API base** (same as `https://` + `API_HOST`), because the browser loads the approval UI from `UI_HOST` and calls the API from the user’s machine.

**Also set:**

- **`ACME_EMAIL`** — Let’s Encrypt account email (required by Caddy in production compose).
- **`CORS_ALLOW_ORIGINS`** — Exactly your UI origin, e.g. `https://parking.example.com` (no trailing slash). Multiple origins: comma-separated.
- **`INTERNAL_API_KEY`** — Strong random secret; then every `POST /internal/*` must send header `X-Internal-Key: <value>` (e.g. from your automation or manual curl). Leave empty only for a closed test window.

## 5. Start the stack

From repo root:

```bash
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env up -d --build
```

**Faster API deploys (optional):** use a pre-built image from GHCR — [GHCR-DEPLOY.md](GHCR-DEPLOY.md) and `deploy/docker-compose.production.ghcr.yml` (set `API_IMAGE` in `deploy/.env`).

Caddy obtains certificates automatically once DNS points at the Droplet and ports **80/443** are reachable.

## 6. Migrate database

Migrations run when the **api** container starts (`alembic upgrade head` in `Dockerfile.backend` CMD). If the first boot fails on PostGIS, enable the extension (step 1) and restart:

```bash
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env restart api worker
```

## 7. Smoke test (Washington config)

Replace `api.parking.example.com` with your real `API_HOST`. If `INTERNAL_API_KEY` is set, add `-H "X-Internal-Key: $INTERNAL_API_KEY"` to internal calls.

```bash
export API_HOST=api.parking.example.com
curl -sS "https://${API_HOST}/health"
curl -sS "https://${API_HOST}/ready"
# Sample ingest (guard with X-Internal-Key when INTERNAL_API_KEY is set):
curl -sS -X POST "https://${API_HOST}/internal/ingest/sample" ${INTERNAL_API_KEY:+-H "X-Internal-Key: $INTERNAL_API_KEY"}
curl -sS "https://${API_HOST}/parcels"
```

Point a DigitalOcean **Uptime** check at `https://${API_HOST}/ready` (expect **200**).

Open your UI hostname in the browser (same as `UI_HOST` in `.env`) and confirm pending approvals after running a pipeline for a parcel id.

## 8. Operations

- **Logs**: `docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env logs -f api worker`
- **Updates**: `git pull && docker compose ... up -d --build`
- **Backups**: enable automated backups on Managed Postgres in the DO UI; snapshot Droplet or treat it as cattle and rebuild from Terraform + compose.

## Compliance reminder

Washington-specific brokerage, privacy, and UPL rules still apply; keep human approval gates until counsel signs off on templates and outreach (`docs/compliance-checklist.md`).
