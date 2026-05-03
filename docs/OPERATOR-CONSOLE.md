# Operator console (browse DB-backed state)

The **operator console** is a Next.js app at **`/operator`** on the same hostname as the approval UI (`UI_HOST` in Caddy). It helps you:

- **Overview** — export-readiness gaps + scoring summary (via a **server-side** proxy to `/internal/stats/*` so `INTERNAL_API_KEY` never reaches the browser).
- **Parcels** — table + parcel detail with **`owner_outreach_brief`**, workflow runs, latest entitlement score.
- **Deal progress** — workflow runs grouped by **`status`** with links into parcels.
- **Approvals** — same queue/actions as the standalone approval UI.
- **Audit** — recent audit rows.
- **Portfolios** — JSON from **`GET /internal/owners/portfolios-ranked`** (proxied).
- **Outreach pipeline** — qualified parcels (entitlement ≥ pilot floor) with workflow stage, brief, pending approvals — **`GET /internal/pipeline/outreach-board`** (proxied).

### Target deal lifecycle (business)

End-to-end you may track parcels through: **owner contact → negotiation → contract with owner → contract with a development partner → built / parking operational**. The app today focuses on **identifying qualified lots**, **running the scoring/enrichment pipeline**, **human approvals** (memo/contract drafts), and **structured outreach data** — not full CRM or construction milestones. Mapping richer phases (e.g. “under LOI”, “GC engaged”, “grand opening”) into the UI usually means adding an explicit **deal phase** field (or integrating a CRM) later; the outreach pipeline table is the current **pre-contact / pipeline-readiness** view.

## URL

After deploy and Caddy reload:

```text
https://<UI_HOST>/operator
```

If you use alternate HTTPS ports (e.g. **9443**):

```text
https://<UI_HOST>:9443/operator
```

## Security notes

- **`INTERNAL_API_KEY`** is only used in the **operator-console** container (Route Handler → API `http://api:8000`). Do not set it as `NEXT_PUBLIC_*`.
- Read APIs (`GET /parcels`, `/workflow-runs`, `/approvals`, `/audit`) are currently **unauthenticated** on the API — treat network access accordingly (VPN, firewall, future auth layer).
- **Owner “conversations”:** the console surfaces **`owner_outreach_brief`** JSON and audit/system events. Multi-agent **Slack** threads are not imported here yet — see Slack channels for live agent chatter.

## Compose

Service **`operator-console`** in `deploy/docker-compose.production.yml`:

- **`NEXT_PUBLIC_API_URL`** — browser → public API (same as approval UI).
- **`API_SERVER_URL=http://api:8000`** — server-side proxy to the API container.
- **`INTERNAL_API_KEY`** — from `deploy/.env`.

Rebuild after changes:

```bash
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env up -d --build operator-console caddy
```

## Local dev

```bash
cd apps/operator-console
npm install
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 INTERNAL_API_KEY=… API_SERVER_URL=http://127.0.0.1:8000 npm run dev
```

Open **http://127.0.0.1:3000/operator** (basePath).
