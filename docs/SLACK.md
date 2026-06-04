# Slack integration

The stack can post a **recurring “agent standup”** to a Slack channel: one Block Kit message **every hour (UTC, top of the hour by default)** summarizing what the pipeline has been doing (new parcels, workflow status changes, pending human approvals, recent audit lines). **Once per day (14:00 UTC)** it also posts a **qualified-parcels report**: latest score per parcel vs `qualified_min_score` from the pilot config, with a short **why** line (zoning, lot size, corner, demand) for qualified rows and a sample of not-qualified rows.

Separately, you can configure a **dedicated “agent discussion” channel** where the two deterministic scoring agents post three messages: **Atlas** (entitlement lens), **Beacon** (demand/visibility lens), then a **joint comparison** (consensus + disagreements). This is **outbound notification**, not a full chat employee — see [Limits](#limits-and-future-work) below.

## Non-sensitive pilot data

The data agents work on here (parcel attributes, scores, workflow status, sample/bundled GeoJSON) is **not sensitive**. Posting digests or optional agent lines to Slack is fine from a data-classification standpoint—use Slack for visibility. You should still **protect the bot token** (`SLACK_BOT_TOKEN`); it is a credential, not the parcel payload.

## What runs where

| Component | Role |
|-----------|------|
| **Celery Beat** (`beat` service in compose) | Sends Slack tasks **hourly** (standup), **daily 14:00 UTC** (qualified parcels), and **daily 15:30 UTC** (dual-agent discussion). |
| **Celery worker (`worker-slack`)** | Dedicated **`slack`** queue — runs digest/report/discussion tasks so pipeline backlog on `worker` cannot block standups. |
| **Celery worker (`worker`)** | **`parking`** queue only — pipelines, ingest, scoring batches (does not consume Slack tasks). |
| **FastAPI** | `POST /internal/slack/digest-now`, `POST /internal/slack/qualified-parcels-now`, and `POST /internal/slack/agent-discussion-now` enqueue the matching tasks (manual test; requires `X-Internal-Key` when `INTERNAL_API_KEY` is set). |

If Slack env is unset, tasks **no-op** (return `skipped` in the task result) so stacks without Slack keep working. The dual-agent discussion needs **`SLACK_BOT_TOKEN`** and **`SLACK_AGENT_DISCUSSION_CHANNEL_ID`**.

## Cursor `@Cursor settings` vs this app's Slack bot

The `@Cursor settings` message in Slack is handled by **Cursor Cloud Agents**, not by this repository. Use it in each **public** Slack channel to set that channel's default repository (for example, this repo for `#cursor-parkinglot-parking` and a different repo for a different channel). Cursor also lets operators override routing by naming the repo in the prompt, and team routing rules live in the Cursor dashboard under **Cloud Agents → Routing Rules**.

The env vars in this document configure this app's own Slack bot: scheduled digests, watchdog alerts, deploy/test pings, and the optional `/parking` command. They do **not** assign Cursor Cloud Agent repositories to Slack channels.

### Per-task “agent” updates (optional)

Set **`SLACK_AGENT_EVENT_UPDATES=1`** (or `true` / `yes` / `on`) in the same env as the **Celery worker** (and API if you want `GET /internal/slack/status` to report the flag). When Slack is fully configured, the worker posts short messages for:

- **Ingest agent** — after each `ingest_geojson_path` run (counts + optional pipeline enqueue summary).
- **Scoring & pipeline agent** — on each `run_pipeline` success or failure (includes a **Human-gate coordinator** line on success: pending approvals).

Leave unset in production if you only want the **scheduled digest** (hourly UTC by default) and manual/API test messages — bulk ingest can generate many Slack lines.

**Production compose:** the **`api`** service receives the same **`SLACK_*`** variables as **worker** / **beat** so `GET /internal/slack/status` and **`POST /internal/slack/test-message`** match the worker’s Slack configuration.

## Slack app setup

1. [Create a Slack app](https://api.slack.com/apps) (From scratch) for your workspace.
2. **OAuth & Permissions** → **Bot Token Scopes** → add **`chat:write`** (post messages).
3. **Install to Workspace** → copy **Bot User OAuth Token** (`xoxb-…`) → set as **`SLACK_BOT_TOKEN`** in `deploy/.env` (or local `.env` for Docker Compose).
4. Open each target channel, run **`/invite @YourBotName`**, or add the app under **Integrations** for that channel.
5. Copy the **channel ID** (e.g. from channel details / URL) → **`SLACK_DIGEST_CHANNEL_ID`** (usually starts with `C`). If discussion or watchdog alerts should go elsewhere, also set **`SLACK_AGENT_DISCUSSION_CHANNEL_ID`** and/or **`SITE_WATCHDOG_SLACK_CHANNEL_ID`**.

Redeploy so **worker**, **worker-slack**, and **beat** pick up env vars. Rebuild or pull a **new API image** that includes the `slack-sdk` dependency (`services/api/pyproject.toml`).

### One command from your laptop (steps 3 + 4)

If the repo is already on the Droplet at `REMOTE_PATH` and **`deploy/.env` exists** there, you can merge Slack lines and restart **worker** + **beat** over SSH:

```bash
chmod +x scripts/set-slack-env-on-droplet.sh
export SLACK_BOT_TOKEN='xoxb-…'
export SLACK_DIGEST_CHANNEL_ID='C…'
# optional, only when these should differ from the digest channel:
# export SLACK_AGENT_DISCUSSION_CHANNEL_ID='C…'
# export SITE_WATCHDOG_SLACK_CHANNEL_ID='C…'
export DROPLET='YOUR_DROPLET_IP_OR_HOST'
# optional: export REMOTE_PATH=/opt/parking-acquisition-agents
# optional: export COMPOSE_FILE=deploy/docker-compose.production.ghcr.yml
./scripts/set-slack-env-on-droplet.sh
```

The script updates `SLACK_BOT_TOKEN` and `SLACK_DIGEST_CHANNEL_ID`; it updates the optional discussion/watchdog channel IDs only when you export them, otherwise existing distinct channel IDs are preserved. It then runs `docker compose … up -d` for **worker**, **worker-slack**, and **beat** only (`pull` first when `COMPOSE_FILE` contains `ghcr`). It cannot run from this chat: you need your real token, channel id, and SSH access.

### Local laptop (repo-root `.env`)

For **`docker compose`** from the repo root (not the Droplet):

```bash
export SLACK_BOT_TOKEN='xoxb-…'
export SLACK_DIGEST_CHANNEL_ID='C…'
# optional, only when these should differ from the digest channel:
# export SLACK_AGENT_DISCUSSION_CHANNEL_ID='C…'
# export SITE_WATCHDOG_SLACK_CHANNEL_ID='C…'
chmod +x scripts/set-slack-env-local.sh
./scripts/set-slack-env-local.sh
# or: make slack-env-local   # same checks + script
docker compose up -d --build worker worker-slack beat
```

Creates **`.env`** from **`.env.example`** if missing, then merges Slack lines.

### Check config from the API

With **`X-Internal-Key`** set as for other `/internal/*` routes:

`GET /internal/slack/status` → `{"slack_digest_configured": true/false, "has_bot_token": ..., "has_digest_channel_id": ..., "slack_channels_distinct": ...}` (no secrets or channel IDs in the body).

`GET /internal/slack/last-digest` → when the **worker** last posted a digest (`audit_log` action `slack_digest_posted`). Use this to confirm Beat → worker → Slack without watching the channel.

### Scheduled digest vs “only works when I’m connected”

The **hourly digest does not use Slack Socket Mode** and does not need your laptop. It is enqueued by the **`beat`** container on the Droplet and executed by **`worker-slack`** (dedicated `slack` queue).

If digests only appear when you are online, typical causes are:

1. **`beat` or `worker-slack` not running** on the Droplet — `docker compose ps beat worker-slack` should show both **Up**.
2. **`SLACK_BOT_TOKEN` / `SLACK_DIGEST_CHANNEL_ID` missing inside worker-slack** — API `test-message` can work while the slack worker skips (`slack_agent_digest SKIPPED` in worker-slack logs). Run `scripts/set-slack-env-on-droplet.sh` and restart **worker**, **worker-slack**, and **beat**.
3. **Local `docker compose` on your Mac** — Beat stops when Docker stops; production must use the Droplet stack.
4. **Stale API image** — pull/redeploy so worker-slack includes `slack-sdk` and the digest task.
5. **Pipeline backlog on `worker`** — should no longer block digests once **`worker-slack`** is deployed; the main **`worker`** only consumes the `parking` queue.

GitHub Actions **Droplet diagnostics** and **Slack digest now** call `scripts/remote/*.sh` on the server (synced on deploy).

## Operations

- **Logs:** `docker compose … logs -f beat worker-slack` — Beat logs schedule ticks; worker-slack logs Slack posts and errors.
- **Send a one-off test message:**  
  `curl -sS -X POST "https://$API_HOST/internal/slack/test-message" -H "X-Internal-Key: $INTERNAL_API_KEY" -H "Content-Type: application/json" -d '{"text":"hello from parking agents"}'`  
  Notes: Slack requires a **channel ID** (not a name). If you want to override the default digest channel, pass `"channel_id":"C…"` (or `G…` for private).
- **Manual fire:**  
  `curl -sS -X POST "https://$API_HOST/internal/slack/digest-now" -H "X-Internal-Key: $INTERNAL_API_KEY"`  
  Then check **`GET /internal/tasks/{task_id}`** for Celery state.
- **Qualified-parcels report (same channel):**  
  `curl -sS -X POST "https://$API_HOST/internal/slack/qualified-parcels-now" -H "X-Internal-Key: $INTERNAL_API_KEY"`  
  Same polling as above. Beat runs this daily; adjust time in `app/celery_app.py` (`slack-qualified-parcels-daily`).
- **Dual-agent discussion (agents-only channel):**  
  `curl -sS -X POST "https://$API_HOST/internal/slack/agent-discussion-now" -H "X-Internal-Key: $INTERNAL_API_KEY"`  
  Beat runs this daily; adjust time in `app/celery_app.py` (`slack-dual-agent-discussion-daily`). You can preview the payload (no posting) via `GET /internal/slack/agent-discussion-preview`.
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
| `not_in_channel` | Bot not invited: **`/invite @YourApp`** in that channel. |
| `channel_not_found` (token OK) | **Wrong channel for this workspace** — copy the ID from Slack (**About / channel details**), or set **`SLACK_DIGEST_CHANNEL_ID=gf-parkinglot-agents-chat`**. |
| `invalid_auth` / `token_revoked` | Regenerate token in Slack app **OAuth** page; update **`SLACK_BOT_TOKEN`** and restart **worker** + **beat**. |
| `missing_scope` | Re-add **`chat:write`** (and reinstall app to workspace). |
| Task returns `skipped` | One of **`SLACK_BOT_TOKEN`** / **`SLACK_DIGEST_CHANNEL_ID`** is empty in the **worker-slack** environment. |

## Limits and future work

- **Replies in Slack are not read** by the app today. The optional Socket Mode service only handles the `/parking` slash command; it does not handle `@Cursor settings`, Slack replies, or repo assignment for Cursor Cloud Agents.
- **Digest content** is derived from the database (parcels, `workflow_runs`, `approval_requests`, `audit_log`). It does not call LLM “agents”; the sections are labeled *Ingest*, *Scoring & pipeline*, etc., as a readable stand-in for operator reporting.
- **Good next steps** if you want “manage like an employee”: (1) Slack slash command → signed request → enqueue Celery task or create `approval_requests`; (2) thread `ts` stored per parcel for continuity; (3) optional LLM summarization of diffs before post.

Security: treat **`SLACK_BOT_TOKEN`** like any other secret ([`SECURITY.md`](../SECURITY.md)).
