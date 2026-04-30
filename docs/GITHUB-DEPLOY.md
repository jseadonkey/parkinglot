# GitHub Actions → DigitalOcean Droplet

Workflow: [`.github/workflows/deploy-droplet.yml`](../.github/workflows/deploy-droplet.yml) (manual **Run workflow** only).

## One-time setup

1. On the Droplet, create **`deploy/.env`** (not in git) with production values — see [GO-LIVE-WASHINGTON-DO.md](GO-LIVE-WASHINGTON-DO.md).
2. In GitHub: **Settings → Secrets and variables → Actions → Secrets**, add:

| Secret | Example |
|--------|---------|
| `DROPLET_HOST` | `203.0.113.10` |
| `DROPLET_USER` | `root` |
| `DROPLET_SSH_PRIVATE_KEY` | Full PEM / OpenSSH private key (include `-----BEGIN` lines) |

3. Optional **Variables** (same settings page → **Variables**):

| Variable | Purpose |
|----------|---------|
| `DROPLET_REMOTE_PATH` | Remote directory (default `/opt/parking-acquisition-agents` if unset) |

4. Run **Actions → Deploy to Droplet → Run workflow**.

Choose **compose file**:

- `docker-compose.production.yml` — build API/worker/UI on the Droplet  
- `docker-compose.production.ghcr.yml` — pull API/worker; set `API_IMAGE` in `deploy/.env`  
- `docker-compose.production.ghcr-full.yml` — pull all app images; set `API_IMAGE` and `APPROVAL_UI_IMAGE` ([GHCR-DEPLOY.md](GHCR-DEPLOY.md), [container-images-ui.yml](../.github/workflows/container-images-ui.yml))

The job rsyncs the repo (excluding `deploy/.env`) then runs `docker compose ... up -d --build` (and **pull** first when using the GHCR compose file). Your secrets on the server stay on the server.

## Optional: pre-built API image

See [GHCR-DEPLOY.md](GHCR-DEPLOY.md) and [`.github/workflows/container-images.yml`](../.github/workflows/container-images.yml). Use `deploy/docker-compose.production.ghcr.yml` plus `API_IMAGE` in `deploy/.env` for pulls instead of builds on the Droplet.
