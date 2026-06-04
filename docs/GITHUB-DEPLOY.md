# GitHub Actions → DigitalOcean Droplet

Workflow: [`.github/workflows/deploy-droplet.yml`](../.github/workflows/deploy-droplet.yml) (manual **Run workflow** only).

## One-time setup

1. On the Droplet, create **`deploy/.env`** (not in git) with production values — see [GO-LIVE-WASHINGTON-DO.md](GO-LIVE-WASHINGTON-DO.md).
2. In GitHub: **Settings → Secrets and variables → Actions → Secrets**, add:

| Secret | Example |
|--------|---------|
| `DROPLET_HOST` | `209.38.142.108` |
| `DROPLET_USER` | `root` |
| `DROPLET_SSH_PRIVATE_KEY` | Full PEM / OpenSSH private key (include `-----BEGIN` lines) |

Optional **Slack ping after deploy** (workflow inputs **slack notify** — see [SLACK.md](SLACK.md#post-deploy-slack-ping-from-github-actions)):

| Secret | Purpose |
|--------|---------|
| `SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY` | Same value as **`INTERNAL_API_KEY`** in the Droplet’s `deploy/.env`, so Actions can call **`POST /internal/slack/test-message`**. Omit only if the API does **not** enforce an internal key (not recommended for production). |

From your laptop (GitHub CLI authenticated for this repo): pipe the **raw key value** (no `INTERNAL_API_KEY=` prefix) on stdin to [`scripts/gh-set-slack-notify-internal-secret.sh`](../scripts/gh-set-slack-notify-internal-secret.sh) — it sets **`SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY`** without using the GitHub web UI.

3. Optional **Variables** (same settings page → **Variables**):

| Variable | Purpose |
|----------|---------|
| `DROPLET_REMOTE_PATH` | Remote directory (default `/opt/workspaces/parkinglot` if unset) |

4. Run **Actions → Deploy to Droplet → Run workflow**.

The workflow validates `DROPLET_HOST`, `DROPLET_USER`, and `DROPLET_REMOTE_PATH`
against [`deploy/droplet.target`](../deploy/droplet.target) before any remote
directory creation, rsync, or rebuild step.

When **Verify /ready** is enabled (default), the job finishes by curling **`PUBLIC_API_URL/ready`** from the Droplet itself. Turn it off if DNS or TLS is not ready yet (first-time bring-up).

Enable **slack notify** on the run form to send a short line to Slack via the API after a successful deploy (requires **`SLACK_BOT_TOKEN`** and channel config on the Droplet, same as digest). Optional **slack notify text** overrides the default; **slack notify channel id** overrides **`SLACK_DIGEST_CHANNEL_ID`** for that ping only.

The **Deploy to Droplet** workflow defaults **use local postgis** to **on** so GitHub Actions keeps `deploy/docker-compose.postgis-addon.yml` in the compose command (your current Droplet layout). Turn it **off** when you move to **Managed Postgres only** (remove `POSTGRES_PASSWORD` / local `DATABASE_URL` first).

**Inspect without redeploying:** [`.github/workflows/droplet-diagnostics.yml`](../.github/workflows/droplet-diagnostics.yml) — **Actions → Droplet diagnostics** — prints `docker compose ps`, recent **api** logs, and optionally the same `/ready` check (only needs `DROPLET_*` secrets). If **`POSTGRES_PASSWORD`** is present in `deploy/.env`, the job automatically adds **`-f deploy/docker-compose.postgis-addon.yml`** so `ps` / logs match the running stack.

**Lightweight HTTP checks:** [`.github/workflows/droplet-endpoint-checks.yml`](../.github/workflows/droplet-endpoint-checks.yml) — **Actions → Droplet endpoint checks** — from the Droplet, curls **`/health`**, **`/ready`**, and optionally **`/internal/slack/status`** (use **`SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY`** when **`INTERNAL_API_KEY`** is set on the server; it must match **`INTERNAL_API_KEY`** in `deploy/.env`). Curls use **`curl -k`** so **internal TLS** (self-signed) on alternate ports still passes. Toggle each check in the run form.

**Slack test without deploy:** [`.github/workflows/slack-test-via-droplet.yml`](../.github/workflows/slack-test-via-droplet.yml) — **Actions → Slack test (via Droplet)** — posts one message via **`/internal/slack/test-message`** (same optional **`SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY`** as post-deploy ping; see [SLACK.md](SLACK.md#slack-test-from-github-actions-no-deploy)).

**Slack digest on demand:** [`.github/workflows/slack-digest-now-via-droplet.yml`](../.github/workflows/slack-digest-now-via-droplet.yml) — **Actions → Slack digest now (via Droplet)** — **`POST /internal/slack/digest-now`** (see [SLACK.md](SLACK.md#enqueue-digest-from-github-actions-no-deploy)).

Choose **compose file**:

- `docker-compose.production.yml` — build API/worker/UI on the Droplet  
- `docker-compose.production.ghcr.yml` — pull API/worker; set `API_IMAGE` in `deploy/.env`  
- `docker-compose.production.ghcr-full.yml` — pull all app images; set `API_IMAGE` and `APPROVAL_UI_IMAGE` ([GHCR-DEPLOY.md](GHCR-DEPLOY.md), [container-images-ui.yml](../.github/workflows/container-images-ui.yml))

The job rsyncs the repo (excluding `deploy/.env`) then runs `docker compose ... up -d --build` (and **pull** first when using the GHCR compose file). Your secrets on the server stay on the server.

## CI failures → Cursor Cloud Agent (laptop can be off)

GitHub failure emails do **not** reach a local Cursor chat. For automatic fixes while your Mac is closed, use a **Cursor Automation** with **Cloud** compute (not Local).

**One-time setup**

1. **Cursor → Automations** — create or save **Fix CI failures on parkinglot (cloud)**:
   - **Trigger:** GitHub → CI checks completed → repo `jseadonkey/parkinglot`
   - **Compute:** **Cloud**
   - **Tools:** open/update PRs, manage check runs
2. **[Cloud Agents dashboard](https://cursor.com/dashboard?tab=cloud-agents)** — enable Cloud Agents; add an environment for this repo (install uses [`.cursor/environment.json`](../.cursor/environment.json)).
3. **Connect GitHub** — Cursor GitHub App with read/write on the repo.

**What the agent should do:** read failing job logs, apply a minimal fix, run `bash scripts/run-api-tests.sh` (or targeted pytest), open a PR. Pilot config paths match CI (`PILOT_*_CONFIG_PATH` in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)).

CI failure → Slack was removed on purpose; operational Slack stays on digests and site watchdog only ([SLACK.md](SLACK.md)).

## Optional: pre-built API image

See [GHCR-DEPLOY.md](GHCR-DEPLOY.md) and [`.github/workflows/container-images.yml`](../.github/workflows/container-images.yml). Use `deploy/docker-compose.production.ghcr.yml` plus `API_IMAGE` in `deploy/.env` for pulls instead of builds on the Droplet.
