# Maryland zoning rules (YAML)

`baltimore_city_surface_parking_rules.yaml` maps **Baltimore City** zone codes (from a spatial join) to **`allows_surface_parking`** for scoring—not legal conclusions; curate with GIS + counsel against **Article 32** use tables.

## Auto-merge at ingest

When **`ZONING_RULES_PATH`** is unset, the API/worker merges (if present):

1. `data/zoning/wa/kent_king_surface_parking_rules.yaml`
2. `data/zoning/wa/wa_county_surface_parking_rules.yaml`
3. `data/zoning/md/baltimore_city_surface_parking_rules.yaml`

Set **`ZONING_RULES_PATH`** to a comma-separated list to override or add files.

## GeoJSON properties (Baltimore overlay)

| Property | Purpose |
|----------|---------|
| `ZONING` / `zoning_code` / `DISTRICT` / `ZONE` | District label from CityView join |
| `ZONING_JURISDICTION` | Use `baltimore_city` (auto-set for county FIPS `24510` if omitted) |
| `ZONING_ALLOWS_SURFACE_PARKING` | Optional bool override (beats YAML) |

See `docs/zoning-sources-baltimore.md` for layer URLs and Phase B steps.

## Before merge (Phase B)

```bash
python3 scripts/validate_phase_b_overlay.py data/baltimore/baltimore_city_zoning_overlay.geojson
```
