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

### Approvals vs research readiness

The pipeline **scores and enriches** in-scope parcels only (**Kent city + unincorporated King County**). Parcels in Seattle, Bellevue, and other King County cities are marked **out of pilot scope** and skipped by default lists, enqueue jobs, and the outreach board. Re-tag after boundary updates: `python3 scripts/apply_pilot_scope.py`.

Deal memo + contract approvals are queued only when **both** latest entitlement and strategic scores meet the pilot floors in `config/pilot.yaml` (same rule as **Outreach pipeline**). Parcels below the floor finish as `completed` with enrichment saved — no human-gate items.

Until **Phase B zoning** and other gaps are filled, most parcels will score low or lack data; expect a **small** qualified set and **do not** bulk-approve memo/contract queues “to clear Slack” unless you have reviewed outreach readiness on each parcel.

## Agent troubleshooting (see what the operator sees)

The agent **cannot** see your browser. To troubleshoot errors and stalled progress, run a **snapshot** that loads the same data every operator page uses:

```bash
cd /opt/workspaces/parkinglot
python3 scripts/operator_console_snapshot.py
python3 scripts/operator_console_snapshot.py --probe-ui   # also checks https://UI_HOST/operator + bridge
python3 scripts/operator_console_snapshot.py --json       # machine-readable for Cursor agents
```

The script reads **`deploy/.env`** (not your browser login). It:

- Calls the **same API routes** as Overview, Parcels, Deals, Approvals, Audit, Portfolios, and Outreach.
- Flags **failed workflow runs**, **pipeline errors**, and large **data gaps** (e.g. missing zoning).
- **Deals / enrich failures:** groups all failed runs by step + error (not limited to 200 UI rows), including sample parcel IDs.
- With **`--probe-ui`**, hits **`https://<UI_HOST>/operator`** and the **server bridge** using **`X-Internal-Key`** (automation bypass in operator-console middleware — key stays on the server).

**When something looks wrong in the UI:** tell the agent “run operator console snapshot” — or paste a screenshot for layout/visual issues the script cannot capture.

**Optional:** screenshots still help for red error banners, login problems, or Caddy/404 issues.

## URL

After deploy and Caddy reload:

```text
https://<UI_HOST>/operator
```

If you use alternate HTTPS ports (e.g. **9443**):

```text
https://<UI_HOST>:9443/operator
```

**Sign-in** for both the approval queue and the operator console uses the same page: **`https://<UI_HOST>[:port]/login`**. If you open `/operator` while logged out, you are redirected there and return to `/operator` after a successful sign-in. (Legacy path `/operator/login` forwards to `/login` as well.)

Use the **same hostname as the approval UI** (`UI_HOST` in `deploy/.env`). Do **not** open the operator console on **`API_HOST`** (the API site only proxies `/` to the FastAPI service — paths like `/operator` there are not the Next app and typically **404**).

### If you see 404 on `/operator`

1. **Hostname** — URL must be `https://<UI_HOST>[:port]/operator`, not `https://<API_HOST>/operator`.
2. **Deploy** — rsync does not overwrite `deploy/.env`, but it **does** update `deploy/Caddyfile`. Run **Deploy to Droplet** (or pull on the server) so Caddy gets the version that routes `/operator` → `operator-console`, then reload Caddy:
   `docker compose ... up -d --build operator-console caddy`
3. **Container** — confirm the service is up: `docker compose ... ps` should show `operator-console` running; check logs if it exits during `npm run build`.
4. **Smoke test on the Droplet** — from the server:
   `docker compose ... exec caddy wget -qO- --timeout=3 http://operator-console:3000/operator | head -c 80`
   You should see HTML (not empty). If that works but the browser 404s, the problem is DNS/TLS/host mismatch, not the app.
5. **404 titled “Parking — approvals”** — Caddy is sending `/operator` to **approval-ui** (wrong upstream). Pull **`deploy/Caddyfile`** (and **`Caddyfile.internal-tls`** if you use alternate HTTPS ports) onto the Droplet, then recreate Caddy so it reloads the mount:  
   `docker compose ... up -d --force-recreate caddy`  
   From repo root on the server, run **`deploy/verify-operator-route-on-droplet.sh`** — it prints the live Caddyfile and wget’s **`operator-console:3000/operator`**. If the script shows `reverse_proxy operator-console` but the browser still 404s, check **`UI_HOST`** in **`deploy/.env`** matches the hostname you type in the browser (no `www.` mismatch).

## Security notes

- **Browser login:** set **`AUTH_SECRET`** and the `AUTH_*` credential variables in `deploy/.env` (see `deploy/env.production.example`). The **approval UI** and **operator console** share the same cookie and env; **admin** can approve/reject, **viewer** is read-only for those actions. Omit **`AUTH_SECRET`** only for local/CI (UIs stay open).
- **`INTERNAL_API_KEY`** is only used in the **operator-console** container (Route Handler → API `http://api:8000`). Do not set it as `NEXT_PUBLIC_*`.
- Read APIs (`GET /parcels`, `/workflow-runs`, `/approvals`, `/audit`) are still **unauthenticated** on the API — the UI login does not protect direct API access; use network controls for that.
- **TLS “not secure”** — If you use **`Caddyfile.internal-tls`** (alternate ports / self-signed), browsers show a certificate warning; that is normal until you terminate trusted TLS at **443** with Let’s Encrypt (`deploy/Caddyfile`) or a reverse proxy with a real certificate.
- **Owner “conversations”:** the console surfaces **`owner_outreach_brief`** JSON and audit/system events. Multi-agent **Slack** threads are not imported here yet — see Slack channels for live agent chatter.

## Compose

Service **`operator-console`** in `deploy/docker-compose.production.yml`:

- **`NEXT_PUBLIC_API_URL`** — browser → public API (same as approval UI).
- **`API_SERVER_URL=http://api:8000`** — server-side proxy to the API container.
- **`INTERNAL_API_KEY`** — from `deploy/.env`.
- **`AUTH_SECRET`**, **`AUTH_ADMIN_*`**, **`AUTH_VIEWER_*`** — optional UI login (same values as **approval-ui**).

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
