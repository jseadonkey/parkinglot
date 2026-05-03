# Operator next steps (session handoff)

Use this file when picking up deploy / phased work after a break. Update **`docs/PROJECT-FACTS.md`** when infra facts change.

## Where things stood (checklist)

- **DNS:** **`parking.vspecialist.com`** and **`api.vspecialist.com`** → **`209.38.142.108`** (records at **GoDaddy** — domain uses **`ns*.domaincontrol.com`**, not DigitalOcean NS).
- **Database:** **`DATABASE_URL`** should point at **DigitalOcean Managed Postgres** (host **`*.db.ondigitalocean.com`**), **not** **`postgres`**.
- **API health:** Inside the **`api`** container, **`http://127.0.0.1:8000/ready`** returned **200** when DB was fixed.
- **Caddy:** Alternate ports often **`CADDY_PUBLISH_HTTP=9080`**, **`CADDY_PUBLISH_HTTPS=9443`**, **`CADDY_CADDYFILE=./Caddyfile.internal-tls`** (self-signed TLS — browsers/`curl` need **`-k`** on HTTPS).

## Likely follow-up on **`deploy/.env`**

Align **`UI_HOST`**, **`API_HOST`**, **`PUBLIC_API_URL`**, **`CORS_ALLOW_ORIGINS`** with **real** **`vspecialist.com`** hostnames — **not** **`parking.example.com`** / **`api.parking.example.com`**. If **`CADDY_PUBLISH_HTTPS=9443`**, **`PUBLIC_API_URL`** and **`CORS_ALLOW_ORIGINS`** usually must include **`:9443`**.

Example (adjust email):

```bash
UI_HOST=parking.vspecialist.com
API_HOST=api.vspecialist.com
PUBLIC_API_URL=https://api.vspecialist.com:9443
CORS_ALLOW_ORIGINS=https://parking.vspecialist.com:9443
ACME_EMAIL=your-real-email@example.com
```

Then:

```bash
cd /opt/workspaces/parkinglot
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env up -d --build caddy api approval-ui
```

## Quick checks

```bash
python3 scripts/check_deploy_env_warnings.py /opt/workspaces/parkinglot
```

From **Mac** (internal TLS + alt port):

```bash
curl -sk -o /dev/null -w "%{http_code}\n" https://api.vspecialist.com:9443/ready
```

## Phases A–E after HTTPS is stable

See **[PHASED-EXECUTION-PLAN-A-E.md](PHASED-EXECUTION-PLAN-A-E.md)** and **[OPERATOR-TODO-BUNDLE.md](OPERATOR-TODO-BUNDLE.md)** — **`execute-phase-a.sh`**, **`execute-phase-b.sh`**, **`execute-phase-c.sh`** need **`DATABASE_URL`** / **`INTERNAL_API_KEY`** / reachable **`PHASE_A_API_BASE`** as documented.
