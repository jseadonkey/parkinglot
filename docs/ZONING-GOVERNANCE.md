# Zoning governance by city/county

Surface-parking zoning is **local**. A zone code only matters after it is mapped to the
specific city/county ordinance use table for **Parking Lot (Principal Use)** or the
local equivalent.

## Required status per market

Every pilot county must have an entry in `data/zoning/governance.yaml`.

| Status | Meaning | Scoring trust |
|--------|---------|---------------|
| `curated` | Rules are mapped to ordinance-backed `P` / `CB` / `CO` / excluded buckets | Can trust zoning score for that jurisdiction, subject to legal review |
| `in_review` | GIS/code source identified, mapping not final | Do not rely on zoning score for decisions |
| `not_started` | No jurisdiction-specific mapping yet | Treat zoning as unknown/conservative |
| `paused` | Market is intentionally inactive | Do not run pipeline based on zoning |

Priority counties in `config/geo_markets.yaml` must be `curated`; otherwise
`make zoning-governance` fails.

## Parcel-loaded county follow-up

Parcel ingest and zoning curation are separate. For Washington, the WaTech parcel
rollout can load a county before that county's city/county zoning sources are
ready. To keep that gap visible, run:

```bash
make zoning-followup-report
```

With `DATABASE_URL` set, this reads live parcel counts and reports every
parcel-loaded WA county whose jurisdiction registry rows are not yet trusted.
The same summary is embedded as `zoning_followup` in:

```bash
GET /internal/ingest/wa-rollout-status
```

Status interpretation:

- `needs_source_discovery` — parcels exist, but registry zoning rows are still
  `not_started`; find official GIS/use-table sources next.
- `in_progress` — a source/layer/rules draft exists; finish joins and QA.
- `blocked` — a public-source blocker exists; choose another source or vendor.
- `trusted` — registered jurisdictions are `qa_passed` / `curated` or
  `not_applicable`.

## Geographic scope (global vs local)

Zoning is local (this doc). Broader product rules live in:

- `config/geo_scope.yaml` — what research/processes are **global** vs state/county/source,
  plus operator list performance budgets (timeouts, overfetch, aerial caps).
- `config/geo_markets.yaml` — which markets are primary / priority counties.

Do **not** hard-code `state_fips == "24"` (or `"53"`) for list timeouts or vacancy SQL.
Assessor field adapters (King Present Use, Baltimore ``NO_IMPRV`` bare-lot flag)
stay source-specific; the *process* that consumes them is global. Do not treat
Baltimore ``VACIND`` (vacant-building notice) as vacant land.

## Scoring policy

- **Permitted / full credit:** only local by-right symbols (Baltimore `P`).
- **Conditional / partial value:** local conditional path (Baltimore `CB` / BMZA).
- **Council/political path:** local legislative path (Baltimore `CO`) — usually defer.
- **Excluded:** principal parking not listed, accessory-only, or unknown.

Unknown codes must remain conservative: `default_when_unknown: false`.

## How to add a city/county

1. Identify the controlling jurisdiction(s): city zoning, unincorporated county zoning,
   overlays, special districts.
2. Add or update the jurisdiction in `data/zoning/governance.yaml`.
3. Add the jurisdiction key to the county coverage entry.
4. Curate that jurisdiction's rules YAML from the official use table.
5. Add common GIS/assessor aliases exactly as they appear in source data.
6. Run:

```bash
make zoning-governance
make run-api-tests
```

7. Only set status to `curated` after the mapping is complete enough for the current
   pilot and documented with a source URL/doc.

## Current state

- **Baltimore City (`24510`)** — curated for Article 32 principal-use surface parking.
- **Baltimore County (`24005`)** — paused; curate before activation.
- **Washington counties (`53*`)** — not started for zoning governance. Parcel ingest can
  continue slowly, but zoning should not be treated as trusted until each city/county
  jurisdiction is mapped.
- **Benton County (`53005`)** — parcels ingested; zoning sources discovered (Kennewick
  attribute join + Pasco/Benton County spatial joins). See `docs/zoning-sources-benton.md`.
  Registry status `source_found` / `in_progress`; not yet `curated`.
