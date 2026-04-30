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

Optional **Slack ping after deploy** (workflow inputs **slack notify** — see [SLACK.md](SLACK.md#post-deploy-slack-ping-from-github-actions)):

| Secret | Purpose |
|--------|---------|
| `SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY` | Same value as **`INTERNAL_API_KEY`** in the Droplet’s `deploy/.env`, so Actions can call **`POST /internal/slack/test-message`**. Omit only if the API does **not** enforce an internal key (not recommended for production). |

3. Optional **Variables** (same settings page → **Variables**):

| Variable | Purpose |
|----------|---------|
| `DROPLET_REMOTE_PATH` | Remote directory (default `/opt/parking-acquisition-agents` if unset) |

4. Run **Actions → Deploy to Droplet → Run workflow**.

When **Verify /ready** is enabled (default), the job finishes by curling **`PUBLIC_API_URL/ready`** from the Droplet itself. Turn it off if DNS or TLS is not ready yet (first-time bring-up).

Enable **slack notify** on the run form to send a short line to Slack via the API after a successful deploy (requires **`SLACK_BOT_TOKEN`** and channel config on the Droplet, same as digest). Optional **slack notify text** overrides the default; **slack notify channel id** overrides **`SLACK_DIGEST_CHANNEL_ID`** for that ping only.

**Inspect without redeploying:** [`.github/workflows/droplet-diagnostics.yml`](../.github/workflows/droplet-diagnostics.yml) — **Actions → Droplet diagnostics** — prints `docker compose ps`, recent **api** logs, and optionally the same `/ready` check (only needs `DROPLET_*` secrets).

**Lightweight HTTP checks:** [`.github/workflows/droplet-endpoint-checks.yml`](../.github/workflows/droplet-endpoint-checks.yml) — **Actions → Droplet endpoint checks** — from the Droplet, curls **`/health`**, **`/ready`**, and optionally **`/internal/slack/status`** (use **`SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY`** when **`INTERNAL_API_KEY`** is set on the server). Toggle each check in the run form.

**Slack test without deploy:** [`.github/workflows/slack-test-via-droplet.yml`](../.github/workflows/slack-test-via-droplet.yml) — **Actions → Slack test (via Droplet)** — posts one message via **`/internal/slack/test-message`** (same optional **`SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY`** as post-deploy ping; see [SLACK.md](SLACK.md#slack-test-from-github-actions-no-deploy)).

Choose **compose file**:

- `docker-compose.production.yml` — build API/worker/UI on the Droplet  
- `docker-compose.production.ghcr.yml` — pull API/worker; set `API_IMAGE` in `deploy/.env`  
- `docker-compose.production.ghcr-full.yml` — pull all app images; set `API_IMAGE` and `APPROVAL_UI_IMAGE` ([GHCR-DEPLOY.md](GHCR-DEPLOY.md), [container-images-ui.yml](../.github/workflows/container-images-ui.yml))

The job rsyncs the repo (excluding `deploy/.env`) then runs `docker compose ... up -d --build` (and **pull** first when using the GHCR compose file). Your secrets on the server stay on the server.

## Optional: pre-built API image

See [GHCR-DEPLOY.md](GHCR-DEPLOY.md) and [`.github/workflows/container-images.yml`](../.github/workflows/container-images.yml). Use `deploy/docker-compose.production.ghcr.yml` plus `API_IMAGE` in `deploy/.env` for pulls instead of builds on the Droplet.
