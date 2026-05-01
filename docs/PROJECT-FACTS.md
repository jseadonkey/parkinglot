# Project facts (operators)

Single place for **names, IDs, and paths** this codebase assumes. Update this file when infra changes so agents and humans stay aligned.

## Product

- **Repo / stack:** `parkinglot` — parcel ingest, scoring, Celery pipelines, optional Approval UI, optional Slack digests.
- **Pilot / scoring config:** `config/pilot.yaml` (mounted read-only in containers).

## DigitalOcean droplet (primary)

| Item | Value |
|------|--------|
| **Public IPv4** | `209.38.142.108` |
| **SSH user** | `cursor` (key-based; `root` also used in some docs) |
| **App path on server** | `/opt/workspaces/parkinglot` |
| **Compose** | `docker compose` from that directory (loads repo-root `.env` for `${SLACK_*}` interpolation) |
| **Optional Slack socket / slash commands** | Service **`slack-socket`** is behind profile **`slack-socket`** (not started by default). Enable with: `docker compose --profile slack-socket up -d slack-socket` (requires `app.slack_socket_runner` in the tree + `SLACK_APP_TOKEN` / `SLACK_SIGNING_SECRET`). |
| **Worker / Beat health** | Compose sets **`healthcheck.disable: true`** on **worker** and **beat** (they do not serve `:8000`; image-level HTTP checks are wrong for Celery). |
| **API (localhost on droplet)** | `http://127.0.0.1:18000` |
| **Deploy / code sync** | Prefer **`git pull`** (or Actions deploy) so **`services/api/app`** stays consistent. Copying single files (e.g. only `internal.py`) can break imports against `models.py` / `schemas.py`. |
| **Internal Slack monitoring** | `GET /internal/slack/status`, `GET /internal/slack/digest-preview`, `POST /internal/slack/digest-now`, `POST /internal/slack/test-message` (some routes require `X-Internal-Key` when `INTERNAL_API_KEY` is set — see `docs/SLACK.md`). |

## Slack (digest + internal routes)

| Item | Value |
|------|--------|
| **Digest channel (human name)** | `#gf-parkinglot-agents-chat` |
| **Digest channel ID** | **`C0B0VPSAH44`** for `#gf-parkinglot-agents-chat` in **Purveyors of Leisure** (copy from **Channel details** in Slack — IDs differ per workspace). Default in `scripts/apply_slack_token.py`. |
| **Env vars** | `SLACK_BOT_TOKEN` (`xoxb-…`), `SLACK_DIGEST_CHANNEL_ID`, optional `SLACK_AGENT_EVENT_UPDATES=1` (worker posts per ingest/pipeline lines — see `docs/SLACK.md`) |
| **Slack & data** | Pipeline inputs and digests are **not sensitive** — OK to post to Slack; still keep **`SLACK_BOT_TOKEN`** secret ([`SLACK.md`](SLACK.md#non-sensitive-pilot-data)). |
| **Production API** | `deploy/docker-compose.production*.yml` pass the same `SLACK_*` values to **`api`** as **worker** / **beat** so `/internal/slack/*` matches digest config. |
| **Apply token on server** | `cd /opt/workspaces/parkinglot && python3 scripts/apply_slack_token.py 'xoxb-…'` |

### Bot name (not in git — fill once)

Slack does **not** store the bot’s **display / @ name** in this repository. It lives only in your Slack workspace and in [api.slack.com/apps](https://api.slack.com/apps) for your app.

**To see the exact name to invite:**

1. Slack (desktop or web) → open `#gf-parkinglot-agents-chat` → type **`@`** → pick your **parking / agents** app from the list (that label is what people @-mention).
2. Or: [api.slack.com/apps](https://api.slack.com/apps) → open **your** app → **Basic Information** → note **App name** (often matches the bot identity users see).

**Record it here after you confirm:**

> **Slack bot @-mention name:** _\<\< fill in once \>\>_

## What cannot be committed

- **`SLACK_BOT_TOKEN`** — workspace secret; keep in droplet `.env` or secret manager, never in git.
- **`INTERNAL_API_KEY`** (if used) — same.

## Related docs

- Slack behavior and smoke tests: [SLACK.md](SLACK.md)
- GitHub deploy + Actions: [GITHUB-DEPLOY.md](GITHUB-DEPLOY.md)
- Day-to-day ops: [OPERATIONS.md](OPERATIONS.md)
