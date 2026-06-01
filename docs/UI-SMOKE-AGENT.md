# Admin UI smoke agent (Playwright)

Browser agent that logs into **vspecialist.com** as admin, visits key pages, and fails if it sees HTTP errors, broken API bridge calls, or missing content.

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

## CI / scheduled agent

GitHub Actions workflow: **Admin UI smoke (browser)** (`.github/workflows/admin-ui-smoke.yml`).

### Required GitHub secrets

| Secret | Purpose |
|--------|---------|
| `UI_SMOKE_ADMIN_EMAIL` | Admin login email |
| `UI_SMOKE_ADMIN_PASSWORD` | Admin login password |

### Optional (Slack alerts to your agents channel)

| Secret | Purpose |
|--------|---------|
| `SLACK_BOT_TOKEN` | Bot token (`xoxb-...`) |
| `SLACK_DIGEST_CHANNEL_ID` | e.g. `#gf-parkinglot-agents-chat` id |

When smoke fails, CI posts a summary to Slack and uploads `smoke-report.json` as an artifact. Re-run the agent in Cursor with that report to fix issues.

## Optional repo variable

| Variable | Default |
|----------|---------|
| `UI_SMOKE_BASE_URL` | `https://vspecialist.com` |
