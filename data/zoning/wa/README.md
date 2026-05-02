# Washington zoning rules (YAML)

`kent_king_surface_parking_rules.yaml` maps **zone codes** (per jurisdiction) to **`allows_surface_parking`** for scoring—not legal conclusions; curate with GIS + counsel.

## Environment override

- **`ZONING_RULES_PATH`** — absolute or relative path to a YAML file. When unset, the API/worker uses (in order): explicit **`zoning_rules_path`** from app settings, then **`/app/data/zoning/wa/kent_king_surface_parking_rules.yaml`** inside Docker (compose mounts repo `data/` → `/app/data`), then **`data/zoning/wa/kent_king_surface_parking_rules.yaml`** relative to the process working directory.

## GeoJSON properties for ingest

| Property | Purpose |
|----------|---------|
| `ZONING` / `zoning_code` | Zone label from the spatial join. |
| `ZONING_JURISDICTION` | `kent_city` or `king_unincorporated`. |
| `ZONING_ALLOWS_SURFACE_PARKING` | Optional; if present, overrides YAML lookup. |

See `docs/zoning-sources-kent.md` for layer URLs.
