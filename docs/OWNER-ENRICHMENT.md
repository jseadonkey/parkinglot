# Owner enrichment ladder

How we go from **taxpayer name on the roll** to **people you can contact** for master-lease outreach.

## Steps (in order)

1. **Tax roll (assessor)** — taxpayer name + mailing address (`owner_record` on parcel detail). Source: King County GIS / eReal Property.
2. **Entity vs individual** — names containing LLC, Inc, Trust, Association, etc. are treated as **companies**.
3. **Companies → underlying people**
   - **Minimum:** mailing address (may be registered agent or CPA).
   - **Washington SOS (CCFS):** registered agent, governors/managers, principal address. Automated when `WA_SOS_LOOKUP_ENABLED=true` (slow — one lookup about every 60 seconds).
   - **Licensed vendor skip-trace** (optional webhook): phone, email, related addresses when configured in `OWNER_VENDOR_LOOKUP_*`.
4. **Individuals** — mailing from roll; phone/email from roll fields or vendor when available.
5. **Human review** — counsel approves channel before any call, text, or email.

## When automation runs

| Tier | When | What runs |
|------|------|-----------|
| **basic** | Parcel below dual score floors | Roll parse only |
| **standard** | Atlas + Beacon dual-qualified | SOS link + portfolio peers + outreach brief |
| **deep** | Dual-qualified + vendor URL configured | Above + vendor webhook for phone/email |

**WA SOS browser lookup** runs on a **separate `sos-worker` container** (Celery queue `sos`), not during normal scoring. Default: ~3 entity lookups every 15 minutes, minimum 60 seconds apart. Main pipeline enqueues entity parcels in the background; it never waits for Playwright.

## Configuration

- `WA_SOS_LOOKUP_ENABLED` — master switch (should be on for `sos-worker` only in production).
- `WA_SOS_INLINE_IN_PIPELINE=false` — **keep false** so scoring never blocks on SOS (default).
- `WA_SOS_MIN_DELAY_SECONDS` — spacing between CCFS calls (default 60).
- `WA_SOS_BEAT_ENABLED` / `WA_SOS_BEAT_LIMIT` / `WA_SOS_BEAT_CRONTAB_MINUTE` — scheduled backlog drain.
- Trigger manually: `POST /internal/metrics/enrich-wa-sos-entities?limit=5` (runs on `sos` queue).

## Operator UI

Parcel detail → **Owner / taxpayer record** (bottom):

- Owner type (company vs individual)
- Enrichment status and gaps
- SOS link for entities
- Underlying people and contacts when found
- **Next steps** checklist

## Vendor skip-trace (BatchData)

BatchData meter (your plan):

| Product | Cost / lookup | We use? |
|---------|---------------|---------|
| **Skip Tracing V3** | **$0.07** | **Yes** — one property per dual-qualified parcel |
| Skip Tracing (sync/async v1–v2) | $0.07 | No — we call V3 endpoint only |
| Property Lookup / Search | $0.015+ | No |
| Property Owner Profile | **$2.00** | No |
| Address Verification / Geocoding | $0.002–0.015 | No |
| Phone DNC / TCPA / Verification | $0.002–0.007 each | No — DNC/TCPA flags in skip-trace response are free metadata, not separate API calls |

**$50 wallet ≈ ~714 skip traces** at $0.07 each (fewer if some parcels are skipped — see below).

- `OWNER_VENDOR_LOOKUP_ENABLED=true` — master switch (only runs on dual-qualified parcels).
- `BATCHDATA_API_KEY` — **Server Side Token** from [app.batchdata.io](https://app.batchdata.io).
- `OWNER_VENDOR_LOOKUP_URL` / `OWNER_VENDOR_LOOKUP_API_KEY` — optional generic webhook instead of BatchData.
- **No re-bill:** prior `batchdata` hit on the parcel brief is reused.
- **No bill:** assessor roll already has both phone and email.

## Not in scope (yet)

- Guaranteed accurate beneficial ownership — always verify with counsel and recorder filings.
