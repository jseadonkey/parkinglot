# Pilot parcel ingest (Kent + unincorporated King funnel)

Shrink a full King County WaTech pull **before** database ingest using a five-layer funnel:

1. **Geography** — Kent city + unincorporated King (same boundaries as `apply_pilot_scope.py`)
2. **Land use** — drop Washington DOR residential codes (`LANDUSE_CD` 11–19 except hotels)
3. **Lot size** — minimum 5,000 sq ft (`Shape__Area` from WaTech)
4. **Zoning** (optional) — attach zone from Kent/King GIS; drop only zones explicitly forbidden in rules YAML
5. **Building value** — drop parcels where `VALUE_BLDG / (VALUE_LAND + VALUE_BLDG) > 0.70` (built-out sites)

## Chunked ingest (recommended for 125k+)

Split the candidate file and ingest in parallel (staggered so workers can also score):

```bash
chmod +x scripts/run_pilot_chunk_ingest.sh scripts/enqueue_pipelines_loop.sh
./scripts/run_pilot_chunk_ingest.sh
```

Split only:

```bash
python3 scripts/split_pilot_geojson.py -i data/pilot/kent_pilot_candidates.geojson -o data/pilot/chunks
```

Logs: `logs/pilot-chunk-ingest.log`, `logs/pilot-pipeline-enqueue.log`, `logs/pilot-parcel-ingest.log`, `logs/pilot-ingest-finalize.log` (and any other `logs/*.log` from scripts). On the Droplet, rotate them with **`sudo ./scripts/install-logrotate.sh`** once — [OPERATIONS.md](OPERATIONS.md#logs-droplet).

## One command (Droplet, repo root)

```bash
cd /opt/workspaces/parkinglot
set -a && source deploy/.env && set +a
chmod +x scripts/run_pilot_parcel_ingest.sh
./scripts/run_pilot_parcel_ingest.sh
```

Requires `KENT_ZONING` and `KING_ZONING` in `deploy/.env` (same as Phase B). Full King County scan can take **1–3+ hours** — run in `tmux` or `screen`.

## Stats only (estimate funnel without ingest)

```bash
PILOT_STATS_ONLY=1 ./scripts/run_pilot_parcel_ingest.sh
```

Or scan first 50k rows:

```bash
PILOT_STATS_ONLY=1 PILOT_FETCH_MAX_SCAN=50000 ./scripts/run_pilot_parcel_ingest.sh
```

## Config

- `config/pilot_parcel_prescreen.yaml` — land-use exclusions, min sqft, zoning mode
- `config/pilot.yaml` — geographic scope (`region.in_scope`)

## Output

- GeoJSON: `data/pilot/kent_pilot_candidates.geojson`
- Ingest uses container path `/app/data/pilot/kent_pilot_candidates.geojson` (bind-mounted from repo `data/`)

After ingest, `./scripts/run_pilot_parcel_ingest.sh` runs `apply_pilot_scope.py` to refresh tags.

## Manual steps

```bash
python3 scripts/fetch_pilot_parcel_candidates.py -o data/pilot/kent_pilot_candidates.geojson

curl -X POST "https://api.vspecialist.com/internal/ingest/geojson-server-path" \
  -H "X-Internal-Key: $(grep '^INTERNAL_API_KEY=' deploy/.env | cut -d= -f2-)" \
  -H "Content-Type: application/json" \
  -d '{"path":"/app/data/pilot/kent_pilot_candidates.geojson","default_county_fips":"53033","auto_run_pipeline":true,"max_auto_pipeline":500}'
```
