# City-level prospect data sources (automated)

Every incorporated place in the parcel DB gets an explicit path for the four
prospect signals. **This is generated, not a human research checklist.**

```bash
# Inside API container (or with DATABASE_URL):
CITY_REGISTRY_CSV=/tmp/city_prospect_sources.csv \
CITY_REGISTRY_DEMAND=/tmp/demand_generators_wa_cities.yaml \
  python /app/scripts/build_city_prospect_registry.py
# then copy outputs into the repo paths below (data/ may be RO in container).
```

## Outputs

| File | Purpose |
|------|---------|
| `data/jurisdictions/city_prospect_sources.csv` | One row per city: parcel / zoning / vacancy / demand source |
| `config/demand_generators_wa_cities.yaml` | Auto centroids (≥25 parcels) merged into pilot demand lists |

## Per-city columns (signals 1–4)

1. **parcel_source** — `watech_current_parcels` (WA) or `baltimore_egis`
2. **zoning_source_kind** — `waza_statewide`, `county_phase_b_overlay`, `city_gis_catalog`, `baltimore_egis_overlay`, or `needs_overlay_or_waza` (queue Phase B / WAZA)
3. **vacancy_source** — `watech_VALUE_BLDG_VALUE_LAND` or Baltimore assessor raw fields
4. **demand_source** — `auto_city_centroid` (this YAML) or county-seat/metro YAML

Re-run after new county ingest. Pilot configs include
`demand_generators_wa_cities.yaml` in `demand_generators_paths`.
