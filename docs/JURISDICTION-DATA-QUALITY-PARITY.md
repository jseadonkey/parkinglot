# Jurisdiction data quality and parity analytics

This workstream answers two questions after parcel/zoning/owner/demand data lands:

1. **Is the data flawed or incomplete?**
2. **Which city/county can be made as good as the best-covered markets with the smallest fixes?**

## What runs

- **API:** `GET /internal/stats/jurisdiction-quality?limit=25`
- **Operator console:** `/operator` -> **Data quality & jurisdiction parity**
- **Slack digest:** the scheduled standup includes a **Data quality / parity agent** section with the top stale gaps.

The report groups parcels by:

```text
county_fips + raw_properties.ZONING_JURISDICTION
```

If `ZONING_JURISDICTION` is missing, rows fall back to `County <FIPS> / jurisdiction unknown`. That fallback is itself useful: it tells us a city/county resolver or overlay needs work.

## What it checks

Per county/city jurisdiction, the report measures missing coverage for:

- footprint / parcel geometry
- zoning code
- lot size
- demand distance
- OSM commercial POI density
- owner roll name
- owner outreach brief
- identification score
- entitlement score
- strategic score

It also calculates:

- **quality_score** — how complete the jurisdiction is across all tracked fields
- **parity_gap_to_best** — how far it is from the best-covered jurisdiction in the database
- **opportunity_score** — a priority score combining parity gap, qualified parcel share, stale gaps, and parcel scale
- **recommended_actions** — next fixes such as zoning overlay, demand refresh, POI density, owner mapping, or pipeline drain

## Hours/days-after-arrival inspection

The report is designed to be run after data arrives, not only during ingest.

It buckets rows by `parcels.created_at`:

- arrived in the last 24 hours
- arrived 1-7 days ago
- arrived more than 7 days ago

It then flags unresolved core gaps that are still present after:

- **24 hours** — likely source, overlay, or pipeline issue
- **7 days** — should be treated as a standing data-quality backlog item

Current limitation: re-ingesting an existing APN updates the row but does **not** update `parcels.created_at`. Refresh activity is still visible through ingest audit events, but true row-level `updated_at` would make this even sharper.

## How to use it

1. Load or refresh a county/city dataset.
2. Let normal scoring/enrichment jobs run.
3. Check `/operator` or call:

   ```bash
   curl -sS "$PUBLIC_API_URL/internal/stats/jurisdiction-quality?limit=25" \
     -H "X-Internal-Key: $INTERNAL_API_KEY"
   ```

4. Prioritize rows with:
   - high `opportunity_score`
   - non-zero `unresolved_core_gaps_older_24h`
   - high missing zoning / demand / owner / score percentages
5. Apply the recommended fix, then rerun the report.

## Typical fixes

| Signal | Likely fix |
|--------|------------|
| Missing zoning | Build/merge zoning overlay; curate rules YAML |
| Jurisdiction unknown | Add city/county resolver or include `ZONING_JURISDICTION` in overlay |
| Missing demand distance | Seed demand generators and run demand refresh |
| Missing POI density | Run POI density refresh batches |
| Missing owner roll name | Fix assessor field mapping before enrichment |
| Missing owner brief | Drain the full pipeline for qualified parcels |
| Missing entitlement/strategic score | Run `enqueue-incomplete` or score refresh jobs |

## Why this matters

This makes multi-county rollout measurable. Instead of asking whether a new city is "good" in general, operators can see exactly which fields keep it behind the current best market and what action would close the gap.
