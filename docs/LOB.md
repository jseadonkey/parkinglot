# Lob certified mail

The stack uses [Lob](https://www.lob.com/) for **printed certified letters** to property owners. Certified mail drafts are rendered from editable templates in the operator console; **nothing is mailed automatically** until counsel approves an `outbound_message` approval and `LOB_SEND_ENABLED=true`.

## What is configured today

| Piece | Status |
|-------|--------|
| Certified mail **templates** + draft previews | Live |
| Human **approval gate** (`outbound_message`) | Live |
| Lob **env + credential check** (`GET /internal/lob/status`, `POST /internal/lob/verify`) | Live |
| Automatic send after approval | Not wired yet — keep `LOB_SEND_ENABLED=false` |

## Lob account setup

1. Sign up at [lob.com](https://www.lob.com/) and open **Settings → API keys**.
2. Copy the **secret** key — **not** the publishable key:
   - **Secret (server):** `test_…` or `live_…` → set as `LOB_API_KEY` (this stack)
   - **Publishable (browser):** `test_pub_…` or `live_pub_…` → not used here; safe for front-end widgets only
3. Use a **test** secret key while validating templates and addresses.
4. Add a **return address** you control — Lob prints this on every letter. Match it to the `LOB_FROM_*` env vars below.
5. When ready for production mail, switch to a **live secret** key and set `LOB_SEND_ENABLED=true` only after legal review.

## Environment variables

Set these in `deploy/.env` on the Droplet (production) or repo-root `.env` (local compose):

| Variable | Required | Notes |
|----------|----------|-------|
| `LOB_API_KEY` | Yes | Lob **secret** key: `test_…` or `live_…` (not `*_pub_*`) |
| `LOB_FROM_NAME` | Yes* | Printed return name (*falls back to `OUTREACH_SENDER_NAME` / `OUTREACH_SENDER_COMPANY`) |
| `LOB_FROM_ADDRESS_LINE1` | Yes | Street address |
| `LOB_FROM_ADDRESS_LINE2` | No | Suite / unit |
| `LOB_FROM_ADDRESS_CITY` | Yes | |
| `LOB_FROM_ADDRESS_STATE` | Yes | Two-letter state |
| `LOB_FROM_ADDRESS_ZIP` | Yes | ZIP or ZIP+4 |
| `LOB_MAIL_EXTRA_SERVICE` | No | Default `certified` |
| `LOB_SEND_ENABLED` | No | Default `false` — future automatic send gate |
| `OUTREACH_SENDER_NAME` | Recommended | Letter signatory + template placeholders |
| `OUTREACH_SENDER_COMPANY` | Recommended | |
| `OUTREACH_SENDER_EMAIL` | Recommended | |
| `OUTREACH_SENDER_PHONE` | Recommended | |

See also `deploy/env.production.example`.

## One command — local laptop

```bash
export LOB_API_KEY='test_...'
export LOB_FROM_NAME='Your Company'
export LOB_FROM_ADDRESS_LINE1='123 Main St'
export LOB_FROM_ADDRESS_CITY='Seattle'
export LOB_FROM_ADDRESS_STATE='WA'
export LOB_FROM_ADDRESS_ZIP='98101'
export OUTREACH_SENDER_NAME='Jane Smith'
export OUTREACH_SENDER_COMPANY='Your Company'
export OUTREACH_SENDER_EMAIL='contact@example.com'
export OUTREACH_SENDER_PHONE='(206) 555-0100'
chmod +x scripts/set-lob-env-local.sh
./scripts/set-lob-env-local.sh
docker compose up -d --build api
```

Or: `make lob-env-local` (same script; requires the exports above).

## One command — Droplet

```bash
export DROPLET='parkinglot'
export LOB_API_KEY='test_...'
export LOB_FROM_NAME='Your Company'
export LOB_FROM_ADDRESS_LINE1='123 Main St'
export LOB_FROM_ADDRESS_CITY='Seattle'
export LOB_FROM_ADDRESS_STATE='WA'
export LOB_FROM_ADDRESS_ZIP='98101'
chmod +x scripts/set-lob-env-on-droplet.sh
./scripts/set-lob-env-on-droplet.sh
```

Uses `deploy/docker-compose.production.ghcr.yml` by default and restarts **api** only.

## Verify from the API

With `INTERNAL_API_KEY` set (same as other `/internal/*` routes):

```bash
curl -sS -H "X-Internal-Key: $INTERNAL_API_KEY" \
  https://api.vspecialist.com/internal/lob/status | jq .

curl -sS -X POST -H "X-Internal-Key: $INTERNAL_API_KEY" \
  https://api.vspecialist.com/internal/lob/verify | jq .
```

`lob_configured: true` means API key **and** return address fields are present. `verify` calls Lob’s read-only `GET /v1/addresses` endpoint to confirm the key works.

## Operator workflow (unchanged)

1. Run pipeline → outreach brief on parcel.
2. Preview certified mail draft in operator console (`certified_mail_letter` template).
3. Request / approve `outbound_message` approval for the parcel + channel.
4. *(Future)* Approved certified mail sends via Lob when `LOB_SEND_ENABLED=true`.

See [OPERATIONS.md](./OPERATIONS.md) for draft and approval API details.
