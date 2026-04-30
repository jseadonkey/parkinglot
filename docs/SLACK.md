# Slack integration

The stack can post a **recurring “agent standup”** to a Slack channel: one Block Kit message every **4 hours (UTC)** summarizing what the pipeline has been doing (new parcels, workflow status changes, pending human approvals, recent audit lines). This is **outbound notification**, not a full chat employee — see [Limits](#limits-and-future-work) below.

## What runs where

| Component | Role |
|-----------|------|
| **Celery Beat** (`beat` service in compose) | Sends `slack_agent_digest` to the broker on a cron (`minute=0`, `hour=*/4` UTC). |
| **Celery worker** | Executes `slack_agent_digest`: reads Postgres, calls Slack `chat.postMessage`. |
| **FastAPI** | `POST /internal/slack/digest-now` enqueues the same task (optional manual test; requires `X-Internal-Key` when `INTERNAL_API_KEY` is set). |

If **`SLACK_BOT_TOKEN`** or **`SLACK_DIGEST_CHANNEL_ID`** is unset, the task **no-ops** (returns `skipped` in the task result) so stacks without Slack keep working.

## Slack app setup

1. [Create a Slack app](https://api.slack.com/apps) (From scratch) for your workspace.
2. **OAuth & Permissions** → **Bot Token Scopes** → add **`chat:write`** (post messages).
3. **Install to Workspace** → copy **Bot User OAuth Token** (`xoxb-…`) → set as **`SLACK_BOT_TOKEN`** in `deploy/.env` (or local `.env` for Docker Compose).
4. Open the target channel, run **`/invite @YourBotName`**, or add the app under **Integrations** for that channel.
5. Copy the **channel ID** (e.g. from channel details / URL) → **`SLACK_DIGEST_CHANNEL_ID`** (usually starts with `C`).

Redeploy so **worker** and **beat** pick up env vars. Rebuild or pull a **new API image** that includes the `slack-sdk` dependency (`services/api/pyproject.toml`).

### One command from your laptop (steps 3 + 4)

If the repo is already on the Droplet at `REMOTE_PATH` and **`deploy/.env` exists** there, you can merge Slack lines and restart **worker** + **beat** over SSH:

```bash
chmod +x scripts/set-slack-env-on-droplet.sh
export SLACK_BOT_TOKEN='xoxb-…'
export SLACK_DIGEST_CHANNEL_ID='C…'
export DROPLET='YOUR_DROPLET_IP_OR_HOST'
# optional: export REMOTE_PATH=/opt/parking-acquisition-agents
# optional: export COMPOSE_FILE=deploy/docker-compose.production.ghcr.yml
./scripts/set-slack-env-on-droplet.sh
```

The script strips any previous `SLACK_*` lines, appends the new ones, then runs `docker compose … up -d` for **worker** and **beat** only (`pull` first when `COMPOSE_FILE` contains `ghcr`). It cannot run from this chat: you need your real token, channel id, and SSH access.

### Local laptop (repo-root `.env`)

For **`docker compose`** from the repo root (not the Droplet):

```bash
export SLACK_BOT_TOKEN='xoxb-…'
export SLACK_DIGEST_CHANNEL_ID='C…'
chmod +x scripts/set-slack-env-local.sh
./scripts/set-slack-env-local.sh
# or: make slack-env-local   # same checks + script
docker compose up -d --build worker beat
```

Creates **`.env`** from **`.env.example`** if missing, then merges Slack lines.

### Check config from the API

With **`X-Internal-Key`** set as for other `/internal/*` routes:

`GET /internal/slack/status` → `{"slack_digest_configured": true/false, "has_bot_token": ..., "has_digest_channel_id": ...}` (no secrets in the body).

## Operations

- **Logs:** `docker compose … logs -f beat worker` — Beat logs schedule ticks; worker logs Slack errors.
- **Send a one-off test message:**  
  `curl -sS -X POST "https://$API_HOST/internal/slack/test-message" -H "X-Internal-Key: $INTERNAL_API_KEY" -H "Content-Type: application/json" -d '{"text":"hello from parking agents"}'`  
  Notes: Slack requires a **channel ID** (not a name). If you want to override the default digest channel, pass `"channel_id":"C…"` (or `G…` for private).
- **Manual fire:**  
  `curl -sS -X POST "https://$API_HOST/internal/slack/digest-now" -H "X-Internal-Key: $INTERNAL_API_KEY"`  
  Then check **`GET /internal/tasks/{task_id}`** for Celery state.
- **Schedule:** Defined in `app/celery_app.py` (`beat_schedule`). To change cadence, edit the `crontab` and redeploy Beat.

### Post-deploy Slack ping from GitHub Actions

The **Deploy to Droplet** workflow can call **`POST /internal/slack/test-message`** from the Droplet after `docker compose up` (and after **`/ready`** when verification is enabled), so your channel gets a one-line deploy confirmation.

1. Ensure **`SLACK_BOT_TOKEN`**, **`SLACK_DIGEST_CHANNEL_ID`**, and (recommended) **`INTERNAL_API_KEY`** are set in **`deploy/.env`** on the server.
2. In GitHub → **Actions secrets**, add **`SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY`** with the **same** value as **`INTERNAL_API_KEY`** on the Droplet (so the workflow can send **`X-Internal-Key`**). If the API does not use an internal key, you can omit this secret.
3. Run **Deploy to Droplet** with **slack notify** turned **on**. Leave **slack notify text** empty for a default message (repo, short SHA, link to the workflow run), or set custom text (max 2000 characters). Optional **slack notify channel id** sends to a different channel for that ping only. Whenever you rotate **`INTERNAL_API_KEY`** on the Droplet (for example via [`scripts/droplet-provision-internal-api-key.sh`](../scripts/droplet-provision-internal-api-key.sh)), update GitHub secret **`SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY`** to the **same** value so Actions can still call **`POST /internal/slack/test-message`**.

Details: [GITHUB-DEPLOY.md](GITHUB-DEPLOY.md).

### Slack test from GitHub Actions (no deploy)

Use **Actions → Slack test (via Droplet)** to call **`POST /internal/slack/test-message`** from the Droplet without running **Deploy to Droplet**. Same **`DROPLET_*`** secrets as deploy; optional **`SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY`** matching **`INTERNAL_API_KEY`** on the server. Leave **message text** empty for a default line that includes the workflow run URL, or set custom text (max 2000 characters). **channel id** overrides **`SLACK_DIGEST_CHANNEL_ID`** for that message only.

Workflow file: [`.github/workflows/slack-test-via-droplet.yml`](../.github/workflows/slack-test-via-droplet.yml).

### Enqueue digest from GitHub Actions (no deploy)

**Actions → Slack digest now (via Droplet)** calls **`POST /internal/slack/digest-now`** from the Droplet — same Celery task Beat schedules, useful for an on-demand standup without SSH. Response includes **`task_id`**; poll **`GET /internal/tasks/{task_id}`** (with **`X-Internal-Key`** when required) or watch **worker** logs. Same **`DROPLET_*`** and optional **`SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY`** as the Slack test workflow.

Workflow file: [`.github/workflows/slack-digest-now-via-droplet.yml`](../.github/workflows/slack-digest-now-via-droplet.yml).

## Troubleshooting

| Symptom | What to check |
|--------|----------------|
| Digest never appears | **`GET /internal/slack/status`** — both flags should be true. Worker logs for `slack_agent_digest`. **Beat** container running (`docker compose ps beat`). |
| `not_in_channel` / `channel_not_found` | Bot not invited: **`/invite @YourApp`** in that channel. **`SLACK_DIGEST_CHANNEL_ID`** must match the channel (public `C…`, private often `G…`). |
| `invalid_auth` / `token_revoked` | Regenerate token in Slack app **OAuth** page; update **`SLACK_BOT_TOKEN`** and restart **worker** + **beat**. |
| `missing_scope` | Re-add **`chat:write`** (and reinstall app to workspace). |
| Task returns `skipped` | One of **`SLACK_BOT_TOKEN`** / **`SLACK_DIGEST_CHANNEL_ID`** is empty in the **worker** environment. |

## Limits and future work

- **Replies in Slack are not read** by the app today. There is no Events API, Socket Mode, or slash-command handler, so you cannot “talk back” to the agents through Slack without additional work (public HTTPS endpoint, `Slack-Signature` verification, idempotency, and mapping messages to internal actions).
- **Digest content** is derived from the database (parcels, `workflow_runs`, `approval_requests`, `audit_log`). It does not call LLM “agents”; the sections are labeled *Ingest*, *Scoring & pipeline*, etc., as a readable stand-in for operator reporting.
- **Good next steps** if you want “manage like an employee”: (1) Slack slash command → signed request → enqueue Celery task or create `approval_requests`; (2) thread `ts` stored per parcel for continuity; (3) optional LLM summarization of diffs before post.

Security: treat **`SLACK_BOT_TOKEN`** like any other secret ([`SECURITY.md`](../SECURITY.md)).
