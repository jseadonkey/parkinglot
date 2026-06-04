# Washington zoning rules (YAML)

`kent_king_surface_parking_rules.yaml` and
`pilot_county_unincorporated_surface_parking_rules.yaml` map **zone codes** (per
jurisdiction) to **`allows_surface_parking`** for scoring. The generated
`wa_city_surface_parking_rules_skeleton.yaml` file creates conservative
false-by-default blocks for every Washington city/town jurisdiction key. These
are not legal conclusions; curate with GIS + counsel.

## Environment override

- **`ZONING_RULES_PATH`** — comma-separated YAML paths (optional). When unset,
  ingest **merges** registry-declared rule files plus WA + MD defaults
  (Docker: `/app/data/zoning/...`). See `docs/GEOGRAPHY-AGENTS.md` for the
  registry/resolver.

## GeoJSON properties for ingest

| Property | Purpose |
|----------|---------|
| `ZONING` / `zoning_code` | Zone label from the spatial join. |
| `ZONING_JURISDICTION` | Optional when the registry can resolve it. Examples: `kent_city`, `king_unincorporated`, `wa_53053_unincorporated`. |
| `ZONING_ALLOWS_SURFACE_PARKING` | Optional; if present, overrides YAML lookup. |

See `docs/zoning-sources-kent.md` for layer URLs.

## Before merge (Phase B)

Dry-run counts with the same property rules as production merge:

```bash
python3 scripts/validate_phase_b_overlay.py /path/to/overlay.geojson
python3 scripts/validate_phase_b_overlay.py --json /path/to/overlay.geojson
```

`scripts/execute-phase-b.sh` runs this automatically unless **`PHASE_B_VALIDATE=0`**.
