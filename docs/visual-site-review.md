# Visual site review (satellite / maps)

After rule-based scoring surfaces a **subset** of parcels (for example high identification / entitlement scores, vacant-ish heuristics), export a shareable CSV and skim candidates from aerial imagery before committing to field visits.

## Workflow

1. **Export** — Run [`scripts/parcel_visual_review_sheet.py`](../scripts/parcel_visual_review_sheet.py) with `DATABASE_URL` set (same Postgres URL as the API). Use `--limit` and optional `--min-score-identification` / `--min-score-entitlement` to keep the list short.
2. **Sort / filter** — Open the CSV in a spreadsheet; sort by score columns as needed.
3. **Review columns** — For each row, open **Google Maps** (satellite at zoom ~18), **OpenStreetMap**, and—**for King County (FIPS 53033) only**—the [King County Parcel Viewer](https://gismaps.kingcounty.gov/parcelviewer2/). Coordinates come from the parcel footprint centroid when geometry exists; rows without footprint have empty map links.
4. **Parcel viewer (King County)** — Deep-linking by APN is not guaranteed stable across releases. The CSV repeats the same base viewer URL for King County rows; paste **APN** into the viewer search or find the parcel manually. For other counties, rely on lat/lon links and county GIS as available.

## Example commands

From repo root (venv with API deps, or droplet checkout):

```bash
export DATABASE_URL='postgresql+psycopg://...'
python3 scripts/parcel_visual_review_sheet.py --limit 100 \
  --min-score-identification 0.45 --min-score-entitlement 0.35 \
  -o parcel_visual_review.csv
```

From the **`api`** container after rebuild (scripts are copied to `/app/scripts`; `PYTHONPATH` points at the API package):

```bash
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env exec api \
  python /app/scripts/parcel_visual_review_sheet.py --limit 80 -o /tmp/review.csv
```

Copy `/tmp/review.csv` off the host if needed (`docker compose cp`, `scp`, etc.).

A fuller CSV without map URLs (more parcel columns) remains [`scripts/export_scored_parcels_csv.py`](../scripts/export_scored_parcels_csv.py); both scripts share [`scripts/parcel_export_common.py`](../scripts/parcel_export_common.py) for the score joins.
