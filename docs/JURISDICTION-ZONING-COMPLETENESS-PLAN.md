# Jurisdiction zoning and value completeness plan

This plan is the operating blueprint for getting every target county and city
into the platform with enough parcel, value, zoning, and entitlement context to
support reliable parking-acquisition screening.

It is intentionally detailed so an engineer or agent can keep executing in
work sessions without repeatedly asking for product direction. It complements:

- [WA_STATEWIDE_ROLLOUT.md](WA_STATEWIDE_ROLLOUT.md) for slow county parcel
  ingest through WaTech.
- [WA_DATA_LAYER_AUTOMATION.md](WA_DATA_LAYER_AUTOMATION.md) for the current
  "layers of truth" implementation order.
- [PHASED-EXECUTION-PLAN-A-E.md](PHASED-EXECUTION-PLAN-A-E.md) for the shipped
  Phase A-E automation and internal endpoints.
- [zoning-sources-kent.md](zoning-sources-kent.md) and
  [zoning-sources-baltimore.md](zoning-sources-baltimore.md) as examples of
  jurisdiction-specific source notes.

## 1. North-star outcome

For every county in the rollout, and every city or unincorporated zoning
authority inside that county, the platform should know:

1. **Parcel anchor**
   - Where parcel polygons come from.
   - Which parcel identifier is stable enough for upserts.
   - How county FIPS and parcel IDs map into the existing ingest contract.
2. **Assessor and value source**
   - Where owner, mailing, tax, land value, improvement value, assessed value,
     market value, sale date, and sale price come from when available.
   - Which fields are authoritative, derived, stale, missing, or license-limited.
3. **Jurisdiction resolver**
   - Whether each parcel is governed by a city zoning code, county
     unincorporated zoning code, special district, overlay, or mixed authority.
   - Which boundary source decides that answer.
4. **Zoning source**
   - The GIS layer, open-data download, vendor feed, ordinance table, or manual
     source for zoning districts.
   - The exact field containing the zone code, district name, overlay name, and
     effective date when available.
5. **Permissible-use interpretation**
   - Whether paid surface parking as a principal use is allowed by right,
     conditional, prohibited, accessory-only, political/discretionary, or unknown.
   - The ordinance section, use table, or staff source that supports that
     interpretation.
6. **Feedback loop**
   - Each adjusted county/city is automatically and manually double-checked
     after changes land.
   - Bad-looking output is corrected before it becomes the default data layer.

The safe default is: **store facts and provenance first; only convert facts into
`zoning_allows_surface_parking=true` when the source supports it.**

## 2. Key definitions

| Term | Meaning in this plan |
|------|----------------------|
| County parcel source | The parcel polygon and assessor-roll source for a county. In Washington, WaTech can provide statewide parcel geometry, but county assessor systems may still be needed for value and owner detail. |
| City zoning authority | An incorporated city that publishes or governs its own zoning. A parcel inside city limits generally should not use county unincorporated zoning rules. |
| County unincorporated zoning authority | The county zoning rules that apply outside incorporated cities and, in some areas, outside special district exceptions. |
| Jurisdiction resolver | The spatial logic that assigns each parcel to the correct zoning authority before zoning is joined. |
| Zoning layer | A polygon layer or equivalent source containing district codes. It is not the same thing as a parcel layer. |
| Use table | The ordinance table or code section that says whether a use such as "parking lot" is permitted, conditional, accessory, or prohibited in a district. |
| Overlay | A spatial or regulatory condition layered on top of base zoning, such as shoreline, historic, airport, downtown design, environmental, or special district rules. |
| Value data | Assessor/tax/sale fields used to understand likely land value, improvement value, assessed value, last sale, and potential acquisition economics. |
| Rules YAML | Repo data file mapping `(zoning_jurisdiction, zone_code)` to scoring facts such as `allows_surface_parking`. Existing examples live under `data/zoning/wa/` and `data/zoning/md/`. |

## 3. Non-negotiable principles

1. **City and county zoning are not interchangeable.** A county parcel layer may
   include parcels inside cities, but the county zoning layer usually does not
   control those city parcels.
2. **Missing beats guessed.** If a zoning use table cannot be verified, mark the
   zone as unknown or not eligible for by-right credit rather than giving it
   full scoring credit.
3. **Conditional is not by-right.** Conditional, council-approved, special use,
   variance, or hearing-based routes can be stored as opportunity context, but
   should not receive the same default score as by-right principal parking.
4. **Accessory parking is not principal paid parking.** A zone allowing parking
   accessory to another use does not automatically permit an independent paid
   surface lot.
5. **Store provenance with every normalized decision.** Every jurisdiction,
   layer, rule, and value field needs source URL, source date, fetch date, and
   interpretation status.
6. **Normalize without flattening nuance.** A standard output schema is required,
   but the plan must preserve notes about special overlays, subdistricts,
   dimensional limits, legacy nonconforming lots, and local terminology.
7. **One feedback loop per jurisdiction.** Every city/county update needs a
   validation pass, sample review, and signoff state before being called "done."

## 4. Current repo capabilities to build on

The repo already has the following automation that should be reused instead of
creating parallel workflows:

| Capability | Existing anchor |
|------------|-----------------|
| Parcel ingest from GeoJSON | `POST /internal/ingest/geojson-upload`, `POST /internal/ingest/geojson-server-path`, `services/ingestion/parking_ingestion/geojson_loader.py` |
| Washington county parcel ingest | `POST /internal/ingest/watech-county`, `scripts/fetch_wa_opendata_parcels.py`, `config/wa_statewide_rollout.yaml` |
| Slow statewide rollout | `docs/WA_STATEWIDE_ROLLOUT.md`, Beat task `wa_statewide_rollout_tick` |
| Attribute-only overlay merge | `POST /internal/ingest/merge-geojson-attributes` |
| Phase B overlay validation | `scripts/validate_phase_b_overlay.py`, `make validate-phase-b-overlay`, `scripts/execute-phase-b.sh` |
| Readiness gap checks | `GET /internal/stats/export-readiness`, `scripts/check_export_readiness.py`, `make readiness` |
| Score and pipeline backfills | Phase A endpoints and `scripts/execute-phase-a.sh` |
| Existing zoning rules | `data/zoning/wa/kent_king_surface_parking_rules.yaml`, `data/zoning/md/baltimore_city_surface_parking_rules.yaml` |
| Example source docs | `docs/zoning-sources-kent.md`, `docs/zoning-sources-baltimore.md` |
| Baltimore overlay example | `scripts/fetch_baltimore_zoning_districts.py`, `scripts/build_baltimore_zoning_overlay.py` |

## 5. Deliverables to create and maintain

The work should produce durable files and repeatable checks, not one-off notes.

### 5.1 Jurisdiction registry

Create a machine-readable registry, preferably:

```text
data/jurisdictions/wa/jurisdiction_registry.csv
```

Minimum fields:

| Field | Required | Notes |
|-------|----------|-------|
| `state_fips` | yes | Washington = `53`; Maryland = `24` for Baltimore examples. |
| `county_fips` | yes | Five-digit county FIPS. |
| `county_name` | yes | Human name. |
| `jurisdiction_type` | yes | `city`, `county_unincorporated`, `countywide`, `special_district`, `tribal`, `unknown`. |
| `jurisdiction_id` | yes | Stable slug such as `kent_city` or `king_unincorporated`. This should match `ZONING_JURISDICTION`. |
| `jurisdiction_name` | yes | Human name. |
| `parent_county_fips` | yes | Same as `county_fips` unless a cross-county city needs multiple rows. |
| `boundary_source_name` | yes | Census TIGERweb, county GIS, city open data, vendor, etc. |
| `boundary_source_url` | yes | URL or file path. |
| `boundary_source_date` | yes | Date shown by source or fetch date when source date is unavailable. |
| `zoning_authority_status` | yes | `not_started`, `source_found`, `layer_downloaded`, `joined`, `rules_drafted`, `qa_passed`, `blocked`, `not_applicable`. |
| `zoning_source_name` | no | GIS/open-data source name. |
| `zoning_source_url` | no | Direct layer, FeatureServer, download, or city planning page. |
| `zoning_code_field` | no | Example: `ZONE`, `DISTRICT`, `CURRZONE`. |
| `zoning_effective_date_field` | no | If available. |
| `use_table_url` | no | Ordinance table or code source. |
| `parking_use_terms` | no | Local terms to search: "parking lot", "commercial parking", "principal use parking", etc. |
| `value_source_status` | yes | `not_started`, `source_found`, `ingested`, `qa_passed`, `blocked`, `not_available`. |
| `value_source_name` | no | Assessor, tax, county open data, vendor. |
| `value_source_url` | no | Direct source. |
| `value_fields_available` | no | Semicolon-separated list. |
| `license_status` | yes | `unknown`, `open`, `restricted`, `requires_vendor`, `no_redistribution`, `blocked`. |
| `last_checked_at` | yes | ISO date. |
| `notes` | no | Concise source or edge-case notes. |

Rules:

- One row per zoning authority, not merely one row per county.
- A city crossing county lines gets one row per county unless the source is
  cleanly statewide and the resolver can handle multi-county geometry.
- `jurisdiction_id` values must be stable because they become data keys in
  overlay files and rules YAML.

### 5.2 Source catalog

Create a source catalog for each state:

```text
data/jurisdictions/wa/source_catalog.csv
```

Minimum fields:

- `source_id`
- `source_type` (`parcel`, `assessor_value`, `zoning_layer`, `boundary`,
  `ordinance`, `overlay`, `vendor`, `manual`)
- `jurisdiction_id`
- `county_fips`
- `source_name`
- `source_url`
- `download_url`
- `api_type` (`arcgis_feature_server`, `arcgis_map_server`, `socrata`,
  `shapefile`, `geojson`, `pdf`, `html_table`, `vendor`, `manual`)
- `license_notes`
- `fetch_method`
- `refresh_frequency_target`
- `last_fetch_at`
- `last_success_at`
- `last_error`
- `provenance_notes`

### 5.3 Boundary files

Store or reference boundaries consistently:

```text
data/boundaries/wa/<jurisdiction_id>.geojson
```

For large or license-restricted boundaries, store metadata and fetch scripts
instead of committing raw data.

Boundary files need:

- Stable CRS: EPSG:4326 unless a script clearly converts it.
- A source note in `data/boundaries/README.md`.
- A registry row tying the file to `jurisdiction_id`.

### 5.4 Raw zoning layer staging

Use a predictable local/staged structure:

```text
data/zoning/raw/wa/<county_fips>/<jurisdiction_id>/
```

Suggested files:

- `source.json` - URL, fetch date, license, field schema.
- `zoning.geojson` - downloaded or normalized zoning polygons when allowed.
- `overlays.geojson` - optional overlay polygons.
- `README.md` - notes that are too detailed for the CSV.

Do not commit restricted data if the license forbids redistribution. In that
case, commit the fetch instructions and source metadata.

### 5.5 Normalized zoning rules

Extend the current rules pattern. For Washington, start with either:

```text
data/zoning/wa/<jurisdiction_id>_surface_parking_rules.yaml
```

or grouped files by county:

```text
data/zoning/wa/<county_fips>_surface_parking_rules.yaml
```

Each rule should preserve more than a boolean:

```yaml
jurisdictions:
  kent_city:
    zones:
      CM:
        allows_surface_parking: true
        entitlement_tier: by_right
        use_category: principal_parking
        ordinance_reference: "Kent zoning code table ..."
        source_url: "https://..."
        source_checked_at: "2026-06-05"
        confidence: medium
        notes: "Verify whether paid public parking differs from accessory parking."
```

Recommended `entitlement_tier` values:

- `by_right`
- `conditional`
- `special_use`
- `council_or_legislative`
- `accessory_only`
- `existing_nonconforming`
- `prohibited`
- `unknown`

Scoring default:

- Only `by_right` should map to `allows_surface_parking: true`.
- Everything else should preserve nuance in notes and receive no by-right
  scoring credit unless counsel or product explicitly decides otherwise.

### 5.6 Normalized parcel/value overlay

Parcel and value overlays should use the existing GeoJSON merge path when the
base parcel already exists in Postgres.

Minimum identity fields:

- `COUNTY_FIPS`
- One of `APN`, `PIN`, `PARCEL_ID`, or whichever alias the loader supports for
  that county.

Recommended value properties:

| Property | Meaning |
|----------|---------|
| `ASSESSED_LAND_VALUE` | Land-only assessed value. |
| `ASSESSED_IMPROVEMENT_VALUE` | Improvement/building assessed value. |
| `ASSESSED_TOTAL_VALUE` | Total assessed value. |
| `MARKET_LAND_VALUE` | Market estimate if county distinguishes it. |
| `MARKET_TOTAL_VALUE` | Market total if county distinguishes it. |
| `TAX_YEAR` | Assessment/tax year. |
| `LAST_SALE_DATE` | Last recorded sale date. |
| `LAST_SALE_PRICE` | Last sale amount. |
| `VALUE_SOURCE` | Source name or ID from source catalog. |
| `VALUE_SOURCE_DATE` | Source vintage or fetch date. |

Value QA should flag:

- Missing land value on otherwise complete parcels.
- Zero values on high-value commercial parcels.
- Values with old tax years.
- Parcels with improvement value far larger than land value when the strategy
  prefers low-improvement surface opportunities.
- Sale price/date fields that are formatted inconsistently.

### 5.7 Normalized zoning overlay

Minimum properties for Phase B:

| Property | Required | Notes |
|----------|----------|-------|
| `COUNTY_FIPS` | yes | Five-digit FIPS. |
| `APN` / `PIN` / `PARCEL_ID` | yes | Must match existing parcel identity. |
| `ZONING` | yes | Base zone code as joined from the correct jurisdiction. |
| `ZONING_JURISDICTION` | yes | Stable registry ID, e.g. `kent_city`. |
| `ZONING_SOURCE` | yes | Source catalog ID or source name. |
| `ZONING_SOURCE_DATE` | yes | Source vintage/fetch date. |
| `ZONING_MATCH_METHOD` | yes | `centroid`, `largest_intersection`, `provided_by_county`, `manual`, `unknown`. |
| `ZONING_MATCH_CONFIDENCE` | yes | `high`, `medium`, `low`. |
| `ZONING_REVIEW_STATUS` | yes | `not_reviewed`, `auto_validated`, `sample_reviewed`, `approved`, `needs_fix`. |
| `ZONING_ALLOWS_SURFACE_PARKING` | no | Only set when intentionally overriding/inlining rule result. |
| `ZONING_NOTES` | no | Boundary, overlay, conditional use, or source nuance. |

Optional overlay properties:

- `ZONING_OVERLAYS`
- `HISTORIC_DISTRICT`
- `SHORELINE_JURISDICTION`
- `AIRPORT_OVERLAY`
- `ENVIRONMENTAL_CRITICAL_AREA`
- `DOWNTOWN_SUBDISTRICT`
- `DESIGN_REVIEW_REQUIRED`
- `MAX_LOT_SIZE_FOR_PARKING`
- `PARKING_USE_TIER`
- `ORDINANCE_REFERENCE`

## 6. Rollout sequence

The sequence below should be repeated in batches. Do not wait for perfect
statewide zoning to keep parcel ingest moving; parcel coverage, value coverage,
zoning coverage, and QA can advance independently as long as status is explicit.

### Wave 0 - Set up tracking and templates

Tasks:

1. Create the jurisdiction registry and source catalog files.
2. Add README files explaining each status field.
3. Add a lightweight validation script for registry rows:
   - required fields present,
   - valid status values,
   - unique `jurisdiction_id`,
   - every rules YAML `jurisdiction_id` exists in registry,
   - every overlay `ZONING_JURISDICTION` exists in registry.
4. Add Makefile targets:
   - `make validate-jurisdictions`
   - `make zoning-coverage-report`
   - `make value-coverage-report`
5. Add a docs index entry linking this plan from existing rollout docs.

Done when:

- New agents can see one registry, one source catalog, and one command that
  fails fast on malformed jurisdiction metadata.

### Wave 1 - County parcel and value completeness

Tasks for each county:

1. Confirm county exists in `config/wa_statewide_rollout.yaml` or the active
   state rollout config.
2. Pull or queue parcel ingest:
   - Washington default: WaTech county ingest.
   - Fallback: county GeoJSON/shapefile export.
   - Vendor: only when public sources are insufficient or license-blocked.
3. Identify assessor/value source:
   - County assessor open data.
   - County tax parcel download.
   - Parcel search export.
   - Licensed vendor.
4. Map value fields to normalized property names.
5. Record source terms:
   - Can we store internally?
   - Can we display to operators?
   - Can we export CSV?
   - Can we redistribute raw geometry?
6. Run ingest or attribute merge.
7. Run readiness checks:
   - `make readiness`
   - `GET /internal/stats/export-readiness`
8. Add source notes to the registry/source catalog.

Done when:

- County parcel count is non-zero.
- Stable parcel ID mapping is documented.
- Value source status is at least `source_found` or explicitly `blocked`.
- Missing value fields are measured, not unknown.

### Wave 2 - Enumerate every city and unincorporated authority

Tasks for each county:

1. Generate the city list from an authoritative boundary source:
   - Census incorporated places as a baseline.
   - County GIS municipal boundaries when more precise.
   - State/local boundary data when available.
2. Add one registry row for:
   - each incorporated city in the county,
   - county unincorporated zoning,
   - special planning districts that publish separate zoning rules,
   - tribal or federal lands if they appear in parcel data and should be
     excluded or separately flagged.
3. Store or reference each boundary.
4. Build a resolver test set:
   - parcels clearly inside each city,
   - parcels clearly unincorporated,
   - parcels near boundaries,
   - parcels intersecting multiple boundaries.
5. Decide resolver method:
   - centroid-in-polygon for most parcels,
   - largest-intersection for parcels crossing boundaries,
   - source-provided jurisdiction when county parcel data has a trusted city
     code,
   - manual exception list for known anomalies.

Done when:

- Every parcel can be assigned one of:
  - a city `jurisdiction_id`,
  - county unincorporated `jurisdiction_id`,
  - excluded/special jurisdiction,
  - unresolved with reason.
- A county-level report shows parcel counts by `ZONING_JURISDICTION`.

### Wave 3 - Discover zoning and use-table sources

Tasks for each jurisdiction:

1. Search for official zoning GIS first:
   - ArcGIS REST service,
   - open-data portal,
   - planning department download,
   - county-hosted city zoning layer.
2. If GIS is not available, identify the next best source:
   - PDF zoning map,
   - static map tiles,
   - municipal code zoning map reference,
   - vendor layer,
   - manual GIS creation from official map.
3. Identify use tables and definitions:
   - Search local code for terms like "parking lot", "commercial parking",
     "public parking", "principal use parking", "surface parking",
     "accessory parking", "parking garage", and "vehicle storage".
   - Capture whether the table distinguishes principal from accessory uses.
4. Identify overlays that can change the answer:
   - downtown subdistricts,
   - shoreline/environmental critical areas,
   - historic districts,
   - airport/port overlays,
   - form-based code districts,
   - design review districts,
   - specific plan areas,
   - maximum lot-size or frontage restrictions for parking.
5. Record source status in the registry.
6. Create or update a jurisdiction source doc when nuance is material.

Done when:

- Each jurisdiction has a zoning source status:
  - `source_found`,
  - `blocked`,
  - `not_available`,
  - or `not_applicable`.
- Each jurisdiction has either a use-table URL or a documented reason it needs
  manual/legal follow-up.

### Wave 4 - Build zoning overlays and rules

Tasks for each jurisdiction or county batch:

1. Download or stage zoning polygons.
2. Normalize geometry to EPSG:4326.
3. Confirm zone code field.
4. Join parcels to the correct zoning source only after jurisdiction resolution.
5. Emit a normalized overlay GeoJSON with the properties in section 5.7.
6. Generate an unknown-zone report:
   - zones present in GIS but missing from rules YAML,
   - zones in rules YAML not present in GIS,
   - parcels with no zoning match,
   - parcels with multiple possible zoning matches.
7. Draft rules YAML:
   - by-right principal paid parking gets `allows_surface_parking: true`,
   - conditional/special/council/accessory/unknown stays false by default,
   - ordinance references and notes are required.
8. Run:
   - `python3 scripts/validate_phase_b_overlay.py <overlay.geojson>`
   - `make validate-phase-b-overlay` when wired for the file.
9. Stage overlay where the worker can read it.
10. Merge with:
    - `scripts/execute-phase-b.sh`, or
    - `POST /internal/ingest/merge-geojson-attributes`.
11. Refresh pipelines for changed parcels.

Done when:

- Overlay validation passes.
- Unknown-zone count is acceptable and documented.
- `export-readiness` zoning gaps drop for the county/jurisdiction.
- A QA sample confirms zones look right in the app/export.

### Wave 5 - Score, export, and review

Tasks:

1. Run Phase A after zoning/value merges:
   - `scripts/execute-phase-a.sh`
   - `make readiness`
2. Run Phase C smoke for owner/portfolio where owner fields are present:
   - `scripts/execute-phase-c.sh`
3. Export a reviewed CSV sample.
4. Compare top parcels before and after the zoning/value adjustment:
   - parcels newly qualified,
   - parcels newly disqualified,
   - parcels with changed entitlement score,
   - parcels with high value but low zoning confidence,
   - parcels with by-right parking but missing value fields.
5. Create a review note for each jurisdiction batch.

Done when:

- The top qualified parcels make intuitive sense for the jurisdiction.
- No obvious city parcel is using county unincorporated zoning.
- No conditional/accessory-only zone is accidentally scored as by-right.
- Value fields are present or explicitly marked unavailable.

### Wave 6 - Refresh and monitor

Tasks:

1. Track refresh cadence in the source catalog.
2. Add stale-source reporting:
   - parcel source stale,
   - value source stale,
   - zoning layer stale,
   - use-table review stale.
3. Add Slack/operator digest lines for:
   - counties pulled,
   - jurisdictions enumerated,
   - jurisdictions QA passed,
   - zoning gaps,
   - value gaps,
   - unknown zones,
   - recent changes needing review.
4. Re-run validation after source refreshes.

Done when:

- The system can tell operators which jurisdictions are fresh, stale, blocked,
  or needing review without opening every source doc manually.

## 7. County-by-county execution checklist

Use this checklist for each county in the rollout.

### 7.1 County setup

- [ ] County FIPS is present in rollout config or active pilot config.
- [ ] County parcel source selected.
- [ ] County parcel source terms reviewed.
- [ ] County parcel ingest command documented.
- [ ] County parcel count after ingest recorded.
- [ ] County assessor/value source selected.
- [ ] Value field mapping drafted.
- [ ] Value source terms reviewed.
- [ ] Value merge/ingest completed or blocked reason recorded.
- [ ] `make readiness` snapshot saved.

### 7.2 City and unincorporated inventory

- [ ] Incorporated places list generated from official boundaries.
- [ ] County unincorporated row added.
- [ ] Special jurisdictions identified.
- [ ] Boundaries staged or referenced.
- [ ] Parcel counts by jurisdiction generated.
- [ ] Boundary-edge sample selected.
- [ ] Resolver method documented.

### 7.3 Zoning sources

- [ ] Zoning GIS source found or blocked.
- [ ] Zone code field identified.
- [ ] Zoning source date/fetch date recorded.
- [ ] Use table found.
- [ ] Parking-use terminology captured.
- [ ] Overlay/special district sources identified.
- [ ] License/ToS noted.
- [ ] Source catalog updated.

### 7.4 Rules and overlay

- [ ] Rules YAML created or updated.
- [ ] Each GIS zone has a rule or unknown status.
- [ ] Ordinance references added for by-right zones.
- [ ] Conditional/special/accessory zones are not marked by-right by default.
- [ ] Overlay GeoJSON produced.
- [ ] Overlay validation passes.
- [ ] Merge executed.
- [ ] Pipeline refresh triggered.
- [ ] Readiness gaps checked after merge.

### 7.5 Feedback loop

- [ ] Automated QA report reviewed.
- [ ] Random sample reviewed.
- [ ] Boundary-edge sample reviewed.
- [ ] Top qualified parcels reviewed.
- [ ] Newly disqualified parcels reviewed.
- [ ] Unknown-zone list reviewed.
- [ ] Values sanity-checked.
- [ ] Fixes applied or follow-up items created.
- [ ] Jurisdiction status moved to `qa_passed` or `needs_fix`.

## 8. Zoning nuance rubric

Different places use different language. Normalize carefully.

| Local finding | Platform interpretation | Default scoring |
|---------------|-------------------------|-----------------|
| Parking lot is listed as permitted/principal/by-right | `entitlement_tier=by_right` | `allows_surface_parking=true` |
| Parking lot requires conditional use permit, hearing examiner, BMZA, special permit, or similar | `entitlement_tier=conditional` or `special_use` | false unless approved override |
| Parking lot requires council ordinance, planned action, rezoning, or development agreement | `entitlement_tier=council_or_legislative` | false unless approved override |
| Only accessory parking is allowed | `entitlement_tier=accessory_only` | false |
| Existing lots may remain, but new principal lots are not allowed | `entitlement_tier=existing_nonconforming` | false unless strategy explicitly targets existing entitled lots |
| Parking is absent from use table | `entitlement_tier=prohibited` or `unknown` depending code structure | false |
| Code distinguishes parking garage from surface lot | Store separate note; do not apply garage permission to surface lot automatically | case-by-case |
| Overlay can prohibit or condition parking | Store overlay and downgrade confidence until reviewed | false or low confidence |
| Dimensional cap applies, such as max lot size | Store cap; flag parcels exceeding cap | by-right only if parcel passes cap |
| Downtown/form-based district discourages standalone lots | Store design/downtown flag; require review | generally false until reviewed |

## 9. Jurisdiction resolver rules

Recommended resolver order:

1. **Excluded/special land first**
   - Tribal, federal, airport, port, railroad, or other land categories if they
     should not follow normal city/county zoning.
2. **City boundary match**
   - If parcel centroid is inside exactly one city boundary, assign that city.
3. **Boundary conflict handling**
   - If parcel intersects multiple city boundaries or centroid is near a
     boundary, use largest intersection and mark confidence `medium`.
4. **Unincorporated fallback**
   - If parcel is inside county but outside incorporated boundaries, assign
     county unincorporated zoning authority.
5. **Manual exception**
   - If source data disagrees or geometry is broken, preserve a manual exception
     list with reason.

QA requirements:

- Report parcel counts per jurisdiction.
- Report parcels assigned `unknown`.
- Report parcels within a small distance of jurisdiction boundaries.
- Review a sample of boundary-near parcels.
- Confirm county unincorporated zoning is not applied inside city limits.

## 10. Feedback loop after every adjustment

Each city/county adjustment should follow the same loop.

### 10.1 Before merge

Run or create automated checks:

1. Overlay file is valid GeoJSON.
2. Required identity fields are present.
3. Required zoning fields are present.
4. Every `ZONING_JURISDICTION` exists in the registry.
5. Every `ZONING` value is either in rules YAML or explicitly reported as
   unknown.
6. No suspicious jurisdiction/source mismatch:
   - city parcel with county unincorporated zoning,
   - county unincorporated parcel with city zoning,
   - cross-county FIPS mismatch.
7. Parcel match rate is measured.
8. Zoning match rate is measured.
9. Value field completeness is measured.

### 10.2 Merge and refresh

1. Stage overlay under repo `data/` or another worker-visible path.
2. Run `scripts/execute-phase-b.sh`.
3. Poll task success.
4. Run `make readiness`.
5. Run pipeline refresh for changed parcels.

### 10.3 Automated after-check

Generate a jurisdiction QA report with:

- total parcels,
- matched parcels,
- unmatched parcels,
- zoning code distribution,
- unknown zone distribution,
- by-right/conditional/accessory/prohibited distribution,
- value field completeness,
- top 25 qualified parcels,
- top 25 parcels removed from qualified list,
- parcels with high score but low zoning confidence,
- parcels with by-right zoning but missing value,
- parcels with high value but no owner,
- parcels near boundaries,
- parcels with overlay conflicts.

Suggested output path:

```text
data/qa/wa/<county_fips>/<jurisdiction_id>/<yyyymmdd>_qa_report.json
data/qa/wa/<county_fips>/<jurisdiction_id>/<yyyymmdd>_qa_report.md
```

### 10.4 Manual/visual review

Review a small but meaningful sample:

- Highest scoring parcels.
- Parcels that newly became qualified.
- Parcels that newly became disqualified.
- Boundary-edge parcels.
- Unknown-zone parcels.
- Parcels in the most common zone.
- Parcels in rare zones.
- Parcels with very high or very low values.

For each sampled parcel, verify:

- It appears in the expected city/county.
- Zoning code matches the official map.
- Permission tier matches the ordinance/use table.
- Value data is plausible.
- Score explanation makes sense.
- The parcel would not embarrass the product if shown to an operator.

### 10.5 Fix loop

If review finds problems:

1. Set registry `zoning_authority_status=needs_fix`.
2. Record issue in jurisdiction notes or QA report.
3. Classify issue:
   - source problem,
   - boundary resolver problem,
   - join problem,
   - rules YAML problem,
   - value mapping problem,
   - scoring weight problem,
   - UI/export presentation problem.
4. Apply fix.
5. Re-run validation, merge, readiness, and sample review.
6. Only move to `qa_passed` after the repeated report looks correct.

## 11. Prioritization logic

Use this order when there are more jurisdictions than can be completed in one
batch:

1. Counties already in active pilot or rollout config.
2. Counties with highest parcel counts and strongest parking opportunity.
3. Cities with the most candidate parcels.
4. Cities containing top-scoring parcels from parcel-only scoring.
5. Unincorporated county areas with significant candidate counts.
6. Jurisdictions with easy official GIS and clear use tables.
7. Jurisdictions with blocked/complex sources after quick wins are complete.

Within Washington, the current county order starts in
`config/wa_statewide_rollout.yaml`:

1. King
2. Pierce
3. Snohomish
4. Kitsap
5. Thurston
6. Skagit
7. Island
8. Clark
9. Spokane
10. Benton
11. Yakima
12. Chelan
13. Clallam
14. Cowlitz
15. Franklin
16. Grant
17. Grays Harbor
18. Kittitas
19. Klickitat
20. Lewis
21. Mason
22. Okanogan
23. Pacific
24. Pend Oreille
25. San Juan
26. Skamania
27. Stevens
28. Wahkiakum
29. Walla Walla
30. Whatcom
31. Adams
32. Asotin
33. Columbia
34. Douglas
35. Ferry
36. Garfield
37. Lincoln
38. Whitman

Do not treat this as final product priority forever. It is an ingest order.
Zoning/value work should still prioritize where candidate parcels and business
value are strongest.

## 12. Recommended engineering backlog

### 12.1 Registry and validation

- [ ] Add `data/jurisdictions/wa/jurisdiction_registry.csv`.
- [ ] Add `data/jurisdictions/wa/source_catalog.csv`.
- [ ] Add schema docs for status enums.
- [ ] Add `scripts/validate_jurisdiction_registry.py`.
- [ ] Add `make validate-jurisdictions`.
- [ ] Add CI coverage for registry validation.

### 12.2 Source discovery helpers

- [ ] Add an ArcGIS layer inspector that records field names, feature counts,
      extents, last edit dates, and download URLs.
- [ ] Add source-catalog update helpers so agents can append new sources
      consistently.
- [ ] Add a zoning-source markdown template.
- [ ] Add a use-table extraction checklist for ordinance pages and PDFs.

### 12.3 Jurisdiction resolver

- [ ] Add boundary ingestion for incorporated places.
- [ ] Add parcel-to-jurisdiction assignment script.
- [ ] Output parcel counts by jurisdiction.
- [ ] Output boundary-edge samples.
- [ ] Add unit tests for centroid/largest-intersection logic.
- [ ] Add manual exception support.

### 12.4 Zoning overlay builder

- [ ] Generalize the Baltimore overlay pattern for any jurisdiction.
- [ ] Support per-jurisdiction zoning layers inside one county batch.
- [ ] Emit required provenance fields.
- [ ] Emit unknown-zone reports.
- [ ] Emit confidence and match method.
- [ ] Keep using `merge-geojson-attributes` for attribute updates.

### 12.5 Rules YAML improvements

- [ ] Extend rules loader to preserve `entitlement_tier`, ordinance reference,
      confidence, and notes even when scoring only needs a boolean.
- [ ] Add validation that by-right zones have ordinance references.
- [ ] Add validation that unknown GIS zones do not silently default to allowed.
- [ ] Add a rules coverage report per jurisdiction.

### 12.6 Value data normalization

- [ ] Add value field aliases to the ingest/merge path if missing.
- [ ] Add value completeness metrics to export readiness.
- [ ] Add suspicious-value QA checks.
- [ ] Add CSV/export columns for normalized value fields if product wants them
      visible.

### 12.7 Feedback loop and reporting

- [ ] Add `scripts/build_jurisdiction_qa_report.py`.
- [ ] Add `make jurisdiction-qa`.
- [ ] Add Markdown and JSON report output.
- [ ] Add before/after score comparison.
- [ ] Add Slack digest counts for jurisdiction status and unknown zones.
- [ ] Add a UI/operator view later if the report proves useful.

## 13. Agent execution prompts

Use prompts like these to keep future agents focused.

### 13.1 County source inventory prompt

```text
For county <COUNTY_NAME> <COUNTY_FIPS>, update the jurisdiction completeness
work. Read docs/JURISDICTION-ZONING-COMPLETENESS-PLAN.md first. Add or update
registry/source-catalog rows for parcel, assessor/value, incorporated city
boundaries, county unincorporated zoning, and known city zoning sources. Do not
guess permissions. Record source URLs, license notes, status, and blockers.
Run registry validation if it exists. Commit and push the docs/data changes.
```

### 13.2 City zoning source prompt

```text
For <JURISDICTION_ID>, find the official zoning GIS layer and use table for
principal paid surface parking. Update the source catalog and create a zoning
source doc if nuance is material. Draft rules YAML entries only where the
ordinance supports them, keeping conditional/accessory/unknown false by
default. Include source URLs and ordinance references. Run validation if
available. Commit and push.
```

### 13.3 Overlay build prompt

```text
Build the Phase B overlay for <COUNTY_FIPS>/<JURISDICTION_ID>. Use the existing
parcel identity fields and required overlay properties from
docs/JURISDICTION-ZONING-COMPLETENESS-PLAN.md. Validate with
scripts/validate_phase_b_overlay.py. Produce unknown-zone and match-rate
summaries. Do not merge until validation passes. Commit scripts/docs changes
and stage generated data only if license permits it.
```

### 13.4 Feedback loop prompt

```text
Run the post-adjustment feedback loop for <COUNTY_FIPS>/<JURISDICTION_ID>.
Compare readiness before/after, inspect zoning distribution, unknown zones,
top qualified parcels, newly qualified parcels, newly disqualified parcels,
boundary-edge parcels, and value completeness. Write a QA report under
data/qa/... or docs/... depending on repo conventions. Mark status qa_passed
only if the sample looks correct; otherwise mark needs_fix with reasons.
```

## 14. Blocker handling

When a source is blocked, do not stall the entire rollout. Record the blocker
and move to the next jurisdiction.

Common blockers and responses:

| Blocker | Response |
|---------|----------|
| Official zoning layer requires login | Record source, license issue, and consider vendor/manual path. |
| Only PDF zoning map exists | Record PDF source, create manual GIS task, keep status `source_found` but not `joined`. |
| Use table is ambiguous | Keep `entitlement_tier=unknown`; do not set allowed by-right. |
| City has no GIS but county hosts city zoning | Use county-hosted layer if official/current; record provenance. |
| Parcel IDs differ across sources | Build a crosswalk or use spatial join; report match rate. |
| City boundary differs by source | Prefer official city/county boundary for zoning; record Census as fallback. |
| License forbids redistribution | Store metadata and fetch instructions, not raw data. |
| Values only available through assessor search | Record manual/vendor requirement; keep value status blocked or requires vendor. |

## 15. Definition of done

### 15.1 County done

A county is complete enough for production screening when:

- Parcel ingest is working and repeatable.
- Value source is ingested, explicitly unavailable, or blocked with reason.
- Every city/unincorporated zoning authority has a registry row.
- Parcel counts by jurisdiction are known.
- Zoning coverage status is known for every jurisdiction.
- At least the priority jurisdictions have overlays merged and QA passed.
- Readiness gaps are measured and acceptable for the current product surface.

### 15.2 Jurisdiction done

A city or unincorporated jurisdiction is complete when:

- Boundary source is recorded.
- Zoning source is recorded.
- Use table/source is recorded.
- Rules YAML covers observed zone codes.
- Overlay merge has run for matching parcels.
- Unknown zones are explained.
- Feedback-loop QA report is clean or issues are documented.
- Status is `qa_passed`.

### 15.3 Rule done

A zoning rule is complete when:

- Zone code matches the GIS value.
- Jurisdiction ID matches registry.
- Permission tier is explicit.
- By-right permission has a citation.
- Conditional/accessory/special cases include notes.
- Source URL and checked date are present.
- The rule passes validation.

## 16. Immediate next implementation slice

Start with the smallest durable scaffolding that improves every future batch:

1. Add jurisdiction registry and source catalog files for Washington.
2. Seed rows for:
   - King County unincorporated,
   - Kent city,
   - Pierce County unincorporated,
   - Snohomish County unincorporated.
3. Add a registry validator script and Make target.
4. Add a zoning-source doc template.
5. Add a QA report template.
6. Use Kent/King as the first end-to-end completed example because source docs
   and rules YAML already exist.
7. Expand to Pierce and Snohomish city inventories after the scaffold is stable.

This creates the operating rail for the larger goal: every county pulled, every
city/county zoning authority understood, every value source tracked, and every
adjustment checked before operators rely on it.
