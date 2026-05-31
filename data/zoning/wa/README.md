# Washington zoning rules (YAML)

`kent_king_surface_parking_rules.yaml` maps **zone codes** (per jurisdiction) to **`allows_surface_parking`** for scoring—not legal conclusions; curate with GIS + counsel.

**Operations context:** flags mean a **primary-use standalone unmanned surface parking** path may exist (see `docs/OPERATIONS-MODEL.md`). Accessory parking-only sites are out of scope even when off-street parking is permitted for another use.

## Environment override

- **`ZONING_RULES_PATH`** — absolute or relative path to a YAML file. When unset, the API/worker uses (in order): explicit **`zoning_rules_path`** from app settings, then **`/app/data/zoning/wa/kent_king_surface_parking_rules.yaml`** inside Docker (compose mounts repo `data/` → `/app/data`), then **`data/zoning/wa/kent_king_surface_parking_rules.yaml`** relative to the process working directory.

## GeoJSON properties for ingest

| Property | Purpose |
|----------|---------|
| `ZONING` / `zoning_code` | Zone label from the spatial join. |
| `ZONING_JURISDICTION` | `kent_city` or `king_unincorporated`. |
| `ZONING_ALLOWS_SURFACE_PARKING` | Optional; if present, overrides YAML lookup. |

See `docs/zoning-sources-kent.md` for layer URLs.

## Before merge (Phase B)

Dry-run counts with the same property rules as production merge:

```bash
python3 scripts/validate_phase_b_overlay.py /path/to/overlay.geojson
python3 scripts/validate_phase_b_overlay.py --json /path/to/overlay.geojson
```

`scripts/execute-phase-b.sh` runs this automatically unless **`PHASE_B_VALIDATE=0`**.
