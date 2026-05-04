# Slack integration

## Fix first: digest scheduled but nothing posts

If **worker** logs show `slack_agent_digest SKIPPED` and **`deploy/.env`** has no **`SLACK_BOT_TOKEN`** / **`SLACK_DIGEST_CHANNEL_ID`**, digests **never leave the server** — Beat still fires every **20 minutes UTC**, tasks succeed immediately with `skipped: True`.

1. Add **`SLACK_BOT_TOKEN`** (`xoxb-…`) and **`SLACK_DIGEST_CHANNEL_ID`** (`C…`) to **`deploy/.env`** on the Droplet (Slack app → **OAuth** → **chat:write** → install → token; channel → copy channel ID → **`/invite @YourBot`**).
2. Recreate worker + beat so containers load env:  
   `docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env up -d worker beat`
3. Confirm: **`python3 scripts/check_ae_setup.py`** shows Slack **OK**, or run **`./scripts/slack_droplet_check.sh`**.

---

## Team reference (fill in for your org)

Use this table so everyone knows **which** Slack workspace and channels this deployment uses. **Do not** put secrets here — only names and optional notes. The bot token and **`C…`** channel IDs stay in **`deploy/secrets.env`** → merged **`deploy/.env`** (never committed).

| | |
|--|--|
| **Slack workspace name** | *(e.g. Acme Corp)* |
| **Digest channel** (20m + daily qualified report) | **Name:** *(e.g. `#parking-agent-feed`)* — env: **`SLACK_DIGEST_CHANNEL_ID`** |
| **Agent discussion channel** (optional dual-agent posts) | **Name:** *(e.g. `#parking-agents-discuss`)* — env: **`SLACK_AGENT_DISCUSSION_CHANNEL_ID`** |

Slack shows the **channel ID** under **View channel details**; the **#channel-name** is what people recognize in the sidebar.

---

The stack can post a **recurring “agent standup”** to a Slack channel: one Block Kit message every **20 minutes (UTC)** summarizing what the pipeline has been doing (new parcels, workflow status changes, pending human approvals, recent audit lines). **Once per day (14:00 UTC)** it also posts a **qualified-parcels report**: latest score per parcel vs `qualified_min_score` from the pilot config, with a short **why** line (zoning, lot size, corner, demand) for qualified rows and a sample of not-qualified rows.

Separately, you can configure a **dedicated “agent discussion” channel** where the two deterministic scoring agents post three messages: **Atlas** (entitlement lens), **Beacon** (demand/visibility lens), then a **joint comparison** (consensus + disagreements). This is **outbound notification**, not a full chat employee — see [Limits](#limits-and-future-work) below.

## Non-sensitive pilot data

The data agents work on here (parcel attributes, scores, workflow status, sample/bundled GeoJSON) is **not sensitive**. Posting digests or optional agent lines to Slack is fine from a data-classification standpoint—use Slack for visibility. You should still **protect the bot token** (`SLACK_BOT_TOKEN`); it is a credential, not the parcel payload.

## What runs where

| Component | Role |
|-----------|------|
| **Celery Beat** (`beat` service in compose) | Sends `slack_agent_digest` every **20 minutes** (`minute=*/20` UTC), `slack_qualified_parcels_report` once daily (**14:00 UTC**), and `slack_dual_agent_discussion` once daily (**15:30 UTC**). |
| **Celery worker** | Executes those tasks: reads Postgres, calls Slack `chat.postMessage` to **`SLACK_DIGEST_CHANNEL_ID`** (digest/verified channel) and optionally **`SLACK_AGENT_DISCUSSION_CHANNEL_ID`** (agents-only channel). |
| **FastAPI** | `POST /internal/slack/digest-now`, `POST /internal/slack/qualified-parcels-now`, and `POST /internal/slack/agent-discussion-now` enqueue the matching tasks (manual test; requires `X-Internal-Key` when `INTERNAL_API_KEY` is set). |

If Slack env is unset, tasks **no-op** (return `skipped` in the task result) so stacks without Slack keep working. The dual-agent discussion needs **`SLACK_BOT_TOKEN`** and **`SLACK_AGENT_DISCUSSION_CHANNEL_ID`**.

### Per-task “agent” updates (optional)

Set **`SLACK_AGENT_EVENT_UPDATES=1`** (or `true` / `yes` / `on`) in the same env as the **Celery worker** (and API if you want `GET /internal/slack/status` to report the flag). When Slack is fully configured, the worker posts short messages for:

- **Ingest agent** — after each `ingest_geojson_path` run (counts + optional pipeline enqueue summary).
- **Scoring & pipeline agent** — on each `run_pipeline` success or failure (includes a **Human-gate coordinator** line on success: pending approvals).

Leave unset in production if you only want the **scheduled digest** (every 20 minutes UTC) and manual/API test messages — bulk ingest can generate many Slack lines.

**Production compose:** the **`api`** service receives the same **`SLACK_*`** variables as **worker** / **beat** so `GET /internal/slack/status` and **`POST /internal/slack/test-message`** match the worker’s Slack configuration.

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
  Then check **`GET /internal/tasks/{task_id}`** for Celery state — or run **`./scripts/slack_digest_now_wait.sh`** (sources **`deploy/.env`**, POSTs digest, polls to **SUCCESS**/**FAILURE**). To poll any task id: **`./scripts/poll_internal_celery_task.sh <task_id>`**.
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

**On the Droplet (repo root):** run **`./scripts/slack_droplet_check.sh`** — checks **beat/worker** are up, **worker** has **`SLACK_*`** set (without printing tokens), **`GET /internal/slack/status`**, and greps recent **worker**/**beat** logs for Slack lines. Minimal cloud images may not have **`make`**; the script does not require it. Equivalent: **`make slack-droplet-check`** after **`sudo apt install -y make`**.

| Symptom | What to check |
|--------|----------------|
| Digest never appears | **`GET /internal/slack/status`** — **`slack_digest_configured`** should be **true** (API reads same **`deploy/.env`** as compose). **`docker compose ps`** — **worker** and **beat** must be running (Beat enqueues; worker posts). After editing **`deploy/.env`**, recreate **`worker`** + **`beat`**: `docker compose … up -d worker beat`. |
| Wrong time / “nothing at lunch” | Schedule is **UTC**: digest **every `:00,:20,:40` UTC**, not local time. See **`services/api/app/celery_app.py`** (`minute=*/20`). |
| Digest never appears (status true) | Confirm **worker** env: `docker compose … exec worker sh -c 'echo -n SLACK_BOT_TOKEN=; test -n "${SLACK_BOT_TOKEN:-}" && echo set || echo MISSING'`. If **MISSING**, compose did not inject vars — fix **`deploy/.env`** + **`up -d worker beat`**. |
| `not_in_channel` | Bot not invited: **`/invite @YourApp`** in that channel. |
| `channel_not_found` (token OK) | **Wrong channel for this workspace** — copy the channel ID from Slack (**About / channel details**). Value looks like **`C01234567890`** (public) or **`G…`** (private). |
| `invalid_auth` / `token_revoked` | Regenerate token in Slack app **OAuth** page; update **`SLACK_BOT_TOKEN`** and restart **worker** + **beat**. |
| `missing_scope` | Re-add **`chat:write`** (and reinstall app to workspace). |
| Task returns `skipped` | Celery task exited early: **`SLACK_BOT_TOKEN`** or **`SLACK_DIGEST_CHANNEL_ID`** empty in **worker** env. Check worker logs for **`slack_agent_digest SKIPPED`**. |
| Redis / Celery broken | If **`POST /internal/slack/digest-now`** returns **`task_id`** but **`GET /internal/tasks/{id}`** stays **PENDING** forever, **worker** is not consuming Redis (`docker compose logs worker`). |

## Limits and future work

- **Replies in Slack are not read** by the app today. There is no Events API, Socket Mode, or slash-command handler, so you cannot “talk back” to the agents through Slack without additional work (public HTTPS endpoint, `Slack-Signature` verification, idempotency, and mapping messages to internal actions).
- **Digest content** is derived from the database (parcels, `workflow_runs`, `approval_requests`, `audit_log`). It does not call LLM “agents”; the sections are labeled *Ingest*, *Scoring & pipeline*, etc., as a readable stand-in for operator reporting.
- **Good next steps** if you want “manage like an employee”: (1) Slack slash command → signed request → enqueue Celery task or create `approval_requests`; (2) thread `ts` stored per parcel for continuity; (3) optional LLM summarization of diffs before post.

Security: treat **`SLACK_BOT_TOKEN`** like any other secret ([`SECURITY.md`](../SECURITY.md)).
