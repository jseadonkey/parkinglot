# Washington zoning rules (YAML)

`kent_king_surface_parking_rules.yaml` maps **zone codes** (per jurisdiction) to **`allows_surface_parking`** for scoring—not legal conclusions; curate with GIS + counsel.

## Environment override

- **`ZONING_RULES_PATH`** — comma-separated YAML paths (optional). When unset, ingest **merges** WA + MD defaults if present: `data/zoning/wa/kent_king_surface_parking_rules.yaml` and `data/zoning/md/baltimore_city_surface_parking_rules.yaml` (Docker: `/app/data/zoning/...`). See `data/zoning/md/README.md` for Baltimore.

## GeoJSON properties for ingest

| Property | Purpose |
|----------|---------|
| `ZONING` / `zoning_code` | Zone label from the spatial join. |
| `ZONING_JURISDICTION` | `kent_city` or `king_unincorporated`. |
| `ZONING_ALLOWS_SURFACE_PARKING` | Optional; if present, overrides YAML lookup. |

See `docs/zoning-sources-kent.md` for layer URLs.

Benton County (`53005`) overlay workflow: `docs/zoning-sources-benton.md`.

## Before merge (Phase B)

Dry-run counts with the same property rules as production merge:

```bash
python3 scripts/validate_phase_b_overlay.py /path/to/overlay.geojson
python3 scripts/validate_phase_b_overlay.py --json /path/to/overlay.geojson
```

`scripts/execute-phase-b.sh` runs this automatically unless **`PHASE_B_VALIDATE=0`**.
