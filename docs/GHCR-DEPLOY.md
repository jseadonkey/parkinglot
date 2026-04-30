# Deploy from GHCR (no compile on the Droplet)

Three production compose variants:

| File | API / worker | Approval UI | Use when |
|------|----------------|-------------|----------|
| [`deploy/docker-compose.production.yml`](../deploy/docker-compose.production.yml) | Build on Droplet | Build on Droplet | Simplest; you have CPU on the Droplet |
| [`deploy/docker-compose.production.ghcr.yml`](../deploy/docker-compose.production.ghcr.yml) | **Pull** from GHCR | Build on Droplet | Fast API deploys; UI still built with your `PUBLIC_API_URL` |
| [`deploy/docker-compose.production.ghcr-full.yml`](../deploy/docker-compose.production.ghcr-full.yml) | **Pull** | **Pull** | Fastest cold start; UI image must have been built with the **same** `PUBLIC_API_URL` you use in prod |

## 1. Build and push images (GitHub Actions)

**API + worker** — [`.github/workflows/container-images.yml`](../.github/workflows/container-images.yml)

- Runs on **push to `main`** and **workflow_dispatch**.
- Pushes: `ghcr.io/<lowercase-owner>/parking-acquisition-api:latest`, `:sha`, and optional **`extra_tag`** (e.g. `v0.4.0`) when you run workflow manually.

**Approval UI** — [`.github/workflows/container-images-ui.yml`](../.github/workflows/container-images-ui.yml)

- **workflow_dispatch only** (needs your live API URL).
- Input **`public_api_url`**: must equal `PUBLIC_API_URL` in production (e.g. `https://api.example.com`) — it is **baked into** the Next.js client bundle at build time.
- Optional **`extra_tag`** for an additional tag.
- Pushes: `ghcr.io/<owner>/parking-acquisition-approval-ui:latest`, `:sha`, optional extra.

Repo setting: **Actions → General → Workflow permissions → Read and write** (for `GITHUB_TOKEN` to push packages).

## 2. Droplet: `docker login ghcr.io`

Use a PAT with **`read:packages`** (read-only):

```bash
echo 'ghp_xxxxxxxx' | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

## 3. `deploy/.env`

**Partial GHCR** (`docker-compose.production.ghcr.yml`):

```bash
API_IMAGE=ghcr.io/yourgithubuser/parking-acquisition-api:latest
# or pin: .../parking-acquisition-api:v0.4.0
```

**Full GHCR** (`docker-compose.production.ghcr-full.yml`):

```bash
API_IMAGE=ghcr.io/yourgithubuser/parking-acquisition-api:latest
APPROVAL_UI_IMAGE=ghcr.io/yourgithubuser/parking-acquisition-approval-ui:latest
```

`PUBLIC_API_URL`, `UI_HOST`, `API_HOST`, database, Spaces, Caddy, etc. stay the same as standard production.

## 4. Pull and run (Droplet)

**API-only GHCR:**

```bash
docker compose -f deploy/docker-compose.production.ghcr.yml --env-file deploy/.env pull
docker compose -f deploy/docker-compose.production.ghcr.yml --env-file deploy/.env up -d
```

**Full GHCR:**

```bash
docker compose -f deploy/docker-compose.production.ghcr-full.yml --env-file deploy/.env pull
docker compose -f deploy/docker-compose.production.ghcr-full.yml --env-file deploy/.env up -d
```

Makefile: `make prod-pull`, `make prod-up-ghcr`, `make prod-pull-full`, `make prod-up-ghcr-full`.

## 5. GitHub Actions deploy workflow

[`.github/workflows/deploy-droplet.yml`](../.github/workflows/deploy-droplet.yml) lets you pick the compose file, including **`docker-compose.production.ghcr-full.yml`**. A **pull** step runs automatically for GHCR compose files before `up`.

## Rebuilding the UI after API URL change

If `PUBLIC_API_URL` changes, **re-run** `container-images-ui.yml` with the new URL and redeploy with a new `APPROVAL_UI_IMAGE` tag (or `:latest` after that build).
