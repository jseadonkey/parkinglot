# Washington zoning preference curation

This is the completion tracker for Washington city/county zoning preference work.

The geography foundation is automated: the registry knows Washington counties,
incorporated places, city boundaries, and default unincorporated jurisdictions.
The remaining work is legal/source curation: each jurisdiction needs
ordinance-backed zone entries that classify whether paid surface parking as a
principal use is preferred, conditional, weak, or excluded.

## Completion definition

Washington zoning curation is complete when every registered WA jurisdiction has
a non-empty rules block with reviewed zone entries in one of:

- `data/zoning/wa/kent_king_surface_parking_rules.yaml`
- `data/zoning/wa/pilot_county_unincorporated_surface_parking_rules.yaml`
- `data/zoning/wa/wa_city_surface_parking_rules_skeleton.yaml`
- future jurisdiction-specific WA rules files referenced from
  `config/geography_registry.yaml`

For each zone, prefer explicit fields:

- `allows_surface_parking: true` only when principal-use paid surface parking is
  permitted by right.
- `principal_use_symbol: P` for permitted, `CB` for conditional/board review,
  `CO` for council/ordinance/legislative path, `NOT_LISTED` or
  `ACCESSORY_ONLY` for excluded.
- `note`, `source_url`, and/or `ordinance_ref` so reviewers can trace the
  decision.

## Status command

```bash
make wa-zoning-curation-status
```

Machine-readable output:

```bash
python3 scripts/check_wa_zoning_curation.py --json
```

Completion gate for future resource runs:

```bash
python3 scripts/check_wa_zoning_curation.py --fail-if-incomplete
```

That command intentionally fails until every WA city/county jurisdiction has
curated zone entries. Use it as the final acceptance check when infrastructure
resources are available to continue the curation work to completion.

## Recommended priority

1. Kent and King County unincorporated.
2. Pierce / Tacoma-area jurisdictions.
3. Snohomish / Everett-area jurisdictions.
4. Kitsap and Thurston.
5. Remaining counties in `config/wa_statewide_rollout.yaml` order, including
   their incorporated cities.

## Safety stance

Unknown or uncurated Washington zoning stays conservative:
`default_when_unknown: false`. Those parcels can still ingest and score on other
signals, but they do not receive favorable-zoning credit until a rules entry is
curated from local ordinance/source material.
