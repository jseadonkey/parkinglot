# Admin UI smoke agent (Playwright)

Browser agent that logs into **vspecialist.com** as admin every **6 hours**, visits key pages, and **always** posts results to your Slack agents channel (where you and Cursor can see them).

## What it checks

After login:

| Page | Path |
|------|------|
| Operator overview | `/operator` |
| Outreach pipeline | `/operator/outreach` |
| Deal progress | `/operator/deals` |
| Approvals | `/operator/approvals` |
| Parcels | `/operator/parcels` |
| Approval home | `/` |

Fails on: navigation HTTP ≥400, visible `HTTP 503` / `404`, failed `/api/bridge/*` or `/api/proxy/*` responses.

## Slack / agent notifications (every run)

| Outcome | Slack message |
|---------|----------------|
| All clear | ✅ Admin UI smoke agent — all clear |
| UI issues | ⚠️ Issues found (list of pages + errors) — **CI fails** |
| Could not run | 🚨 Missing secrets, install failed, or test crashed — **CI fails** |

Posts via **`POST /internal/slack/test-message`** on production API (recommended) so messages land in **`#gf-parkinglot-agents-chat`** — the same channel your other agents use. Forward failures to Cursor in the parkinglot repo.

If reporting fails entirely, the GitHub job fails so you get an email from Actions too.

## GitHub secrets

### Required

| Secret | Purpose |
|--------|---------|
| `UI_SMOKE_ADMIN_EMAIL` | Admin login email |
| `UI_SMOKE_ADMIN_PASSWORD` | Admin login password |

### Required for notifications (one of)

| Secret | Purpose |
|--------|---------|
| `SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY` | Same as `INTERNAL_API_KEY` on Droplet — posts via API to agents channel |
| `SLACK_BOT_TOKEN` + `SLACK_DIGEST_CHANNEL_ID` | Direct Slack fallback |

### Optional variables

| Variable | Default |
|----------|---------|
| `PUBLIC_API_URL` | `https://api.vspecialist.com` |
| `UI_SMOKE_BASE_URL` | `https://vspecialist.com` |

## Run locally

```bash
cd scripts/admin-ui-smoke
npm install
npx playwright install chromium

export UI_SMOKE_BASE_URL=https://vspecialist.com
export UI_SMOKE_ADMIN_EMAIL='your-admin@email.com'
export UI_SMOKE_ADMIN_PASSWORD='your-password'

npm test
```

## CI

**Actions → Admin UI smoke (browser)** — scheduled `15 */6 * * *` UTC and manual.

Report script: `scripts/admin-ui-smoke/report-smoke.py`
