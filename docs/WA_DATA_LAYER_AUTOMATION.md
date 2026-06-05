# Washington (Puget Sound) — automated “layers of truth” roadmap

This doc turns the high-level layer stack into an **implementation sequence** for the pilot counties in `config/pilot.yaml` (typically King `53033`, Snohomish `53061`, Pierce `53053`).

Design goal: **maximize automated evidence gathering + scoring + enrichment** and only use human gates for **legally sensitive outbound actions** (already modeled as approval types in the API).

## What “fully automated” means in this codebase

Automation is implemented as **repeatable jobs** that:

1. fetch/refresh authoritative datasets (with provenance),
2. normalize into parcels / parcel attributes,
3. enqueue `run_pipeline` (scoring → enrichment → outreach brief persistence),
4. emit operator visibility (Slack digest + optional on-demand Slack commands).

There is no magic “browse the whole internet” layer—**each layer must be a concrete connector** (bulk GIS, licensed vendor API, SOS automation, etc.).

## Phase 0 — operational prerequisites (1–2 days)

- **Source of truth inventory** per county: parcel polygon source, roll join keys, zoning jurisdiction resolver inputs.
- **License/ToS matrix**: what can be stored, re-served, derived, and retained.
- **Idempotent ingest contract**: stable `(county_fips, apn/pin)` upserts; re-ingest clears stale scores (already supported).
- **Rate limits + backoff** for any HTTP connectors (SOS, vendor).

Exit criteria: you can answer “where does each field come from?” for Tier 1–3.

## Phase 1 — Tier A: parcel anchor + assessor roll (highest leverage)

Deliverables:

- nightly (or weekly) **parcel polygon refresh** per county into `data/` (or object storage) as GeoJSON
- roll fields embedded in GeoJSON properties (preferred) *or* joined server-side before ingest
- ingest via `ingest_geojson_path` with `auto_run_pipeline=true` (capped) OR ingest then `enqueue-unscored`

Exit criteria:

- parcels table grows/updates with provenance metadata
- `GET /parcels?qualified_only=true` returns stable results after refresh

## Phase 2 — Tier B: jurisdiction + zoning + overlays (biggest “suitability” lift)

Deliverables:

- **jurisdiction resolver**: point-in-polygon against municipal boundaries to choose city vs county zoning layer
- **zoning join**: attach `zoning_code`, permitted uses evidence, overlay hits
- **scoring inputs** updated from joined zoning facts (not just ingest flags)

Exit criteria:

- “qualified” parcels correlate with zoning evidence fields
- scoring notes explain *why* (not just a number)

## Phase 3 — Tier C/D: demand + ROW/access proxies (ranking)

Deliverables:

- replace illustrative `pilot.yaml` demand generators with real submarket POI sets
- optional traffic / street-class penalties where data exists

Exit criteria:

- top qualified list changes when demand config changes (expected sensitivity)

## Phase 4 — Tier E: WA SOS entity enrichment (owner truth beyond roll)

Deliverables:

- batched SOS lookup jobs for entity-shaped owners
- cache results + store structured `registry_lookup` evidence on outreach brief (model supports this)

Exit criteria:

- LLC owners get SOS steps populated with higher confidence when hits exist

## Phase 5 — Tier F: recorded instruments / vendor enrichment (last automated layer)

Deliverables:

- recorder index connector OR vendor webhook enrichment
- conflict detection when roll vs instruments disagree

Exit criteria:

- parcels flagged “title complexity” without human reading every PDF

## Scheduling defaults (recommended)

- **Tier 1 parcel/roll refresh**: nightly (cadastre changes are usually low-frequency)
- **Tier 2 zoning refresh**: weekly (changes more often around rezones, but not hourly)
- **Tier 4 SOS refresh**: weekly + on-demand when owner string changes
- **Slack digest**: hourly UTC by default (already configured via Celery Beat)

## Human gates (should remain last)

Keep human approval for:

- outbound messaging
- contract send/execute
- any “contact owner” action that could create TCPA/CAN-SPAM exposure

Everything above can be automated with audit trails.

## Next engineering tickets (concrete)

1. `wa-parcels-nightly` job: download/export → `ingest_geojson_path` (+ enqueue pipelines)
2. `wa-zoning-weekly` job: build jurisdiction map + join zoning attributes into parcel facts
3. `wa-sos-entity-weekly` job: batch SOS enrichment for entity owners
4. “data quality dashboard” section in Slack digest: % parcels missing zoning, % missing roll owner, SOS hit rate
