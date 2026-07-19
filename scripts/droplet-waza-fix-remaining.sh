#!/usr/bin/env bash
# Fix remaining WA zoning gaps: Current_Parcels re-ingest + WAZA overlay populate + rescore.
# Ferry has no traditional zoning districts — re-ingest parcels only.
# Run on parkinglot Droplet: bash scripts/droplet-waza-fix-remaining.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ "$ROOT" != /opt/workspaces/parkinglot* ]]; then
  echo "error: run on parkinglot Droplet" >&2
  exit 1
fi

COMPOSE=(docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env)
NAME="${1:-waza-fix-remaining}"

echo "Rebuilding worker image..."
"${COMPOSE[@]}" build worker

docker rm -f "$NAME" >/dev/null 2>&1 || true
"${COMPOSE[@]}" run -d --no-deps --name "$NAME" worker python -c "$(cat <<'PY'
import json, traceback
from pathlib import Path
from sqlalchemy import text
from parking_ingestion.wa_county_zoning_build import write_county_zoning_overlay, WAZA_ZONES_LAYER_URL
from parking_ingestion.watech_parcels import WATECH_STATEWIDE_PARCELS_LAYER
from app.db import SessionLocal
from app.tasks import fetch_watech_county_and_ingest, refresh_entitlement_scores_batch

print("WATECH_LAYER", WATECH_STATEWIDE_PARCELS_LAYER, flush=True)

OUT = (
    "ZoneID,ZoneName,Jurisdiction,WAZAZoneGeneral,WAZAZoneSpecific,"
    "UseRetail,UseOffice,UseManufacturing,UseHeavyIndustrial,UseWarehouse"
)
STASH = [
    "ZONING_JURISDICTION", "ZoneName", "WAZAZoneGeneral", "WAZAZoneSpecific",
    "UseRetail", "UseOffice", "UseManufacturing", "UseHeavyIndustrial", "UseWarehouse",
]
# Re-ingest then WAZA-overlay. Ferry: re-ingest only (no traditional zoning / not in WAZA).
REINGEST = [
    ("53075", "075", "whitman"),
    ("53047", "047", "okanogan"),
    ("53003", "003", "asotin"),
    ("53051", "051", "pend_oreille"),
    ("53043", "043", "lincoln"),
    ("53019", "019", "ferry"),
]

UPD = text(
    "UPDATE parcels SET zoning_code=:zc, "
    "raw_properties = coalesce(raw_properties,'{}'::jsonb) || cast(:extra as jsonb) "
    "WHERE county_fips=:cf AND apn=:apn"
)

for fips, cfp, slug in REINGEST:
    try:
        print(f"INGEST_START {fips} {slug}", flush=True)
        ires = fetch_watech_county_and_ingest.run(
            fips, max_features=None, auto_run_pipeline=False, max_auto_pipeline=0
        )
        print(f"INGEST_DONE {fips} {slug} " + json.dumps(
            {k: ires.get(k) for k in ("inserted", "updated", "skipped", "total_features", "features")},
            default=str,
        ), flush=True)
    except Exception as e:
        print(f"INGEST_ERROR {fips} {slug}: {e}", flush=True)
        traceback.print_exc()

    # Ferry County has no traditional zoning districts (county FAQ) and is absent from WAZA.
    if fips == "53019":
        print(f"SKIP_WAZA {fips} ferry: no traditional zoning / not in WAZA", flush=True)
        continue

    try:
        cache = Path(f"/app/data/wa/{fips}")
        overlay = cache / f"{slug}_waza_zoning_overlay.geojson"
        if overlay.is_file():
            overlay.unlink()
        for stale in cache.glob("waza_*_districts.geojson"):
            stale.unlink()
        src = [{
            "source_id": f"waza_{fips}",
            "label": f"WAZA {slug}",
            "layer_url": WAZA_ZONES_LAYER_URL,
            "zoning_field": "ZoneID",
            "zoning_jurisdiction": f"{slug}_waza",
            "jurisdiction_field": "Jurisdiction",
            "jurisdiction_style": "waza",
            "where": f"COUNTYFP='{cfp}'",
            "out_fields": OUT,
            "extra_fields": OUT,
        }]
        bmeta = write_county_zoning_overlay(fips, overlay, cache_dir=cache, zoning_sources=src)
        print(f"BUILD {fips} {slug} features={bmeta.get('feature_count')}", flush=True)

        data = json.load(open(overlay))
        params = []
        for f in data.get("features", []):
            p = f.get("properties") or {}
            apn = p.get("APN")
            zc = p.get("ZONING")
            if not apn or not zc:
                continue
            extra = {k: p[k] for k in STASH if p.get(k) is not None}
            params.append({"zc": str(zc), "extra": json.dumps(extra), "cf": fips, "apn": str(apn)})

        db = SessionLocal()
        upd = 0
        for i in range(0, len(params), 5000):
            chunk = params[i : i + 5000]
            db.execute(UPD, chunk)
            db.commit()
            upd += len(chunk)
            print(f"POPULATE_CHUNK {fips} {slug} +{len(chunk)} total_sent={upd}", flush=True)
        cov = db.execute(
            text("SELECT count(zoning_code), count(*) FROM parcels WHERE county_fips=:cf"),
            {"cf": fips},
        ).first()
        db.close()
        print(
            f"POPULATE {fips} {slug} apn_rows={upd} now_with_zoning={cov[0]}/{cov[1]}",
            flush=True,
        )

        sres = refresh_entitlement_scores_batch(limit=5000, county_fips=fips, process_all=True)
        print(f"RESCORE {fips} {slug} " + json.dumps(sres, default=str), flush=True)
    except Exception as e:
        print(f"ERROR {fips} {slug}: {e}", flush=True)
        traceback.print_exc()

print("WAZA_FIX_REMAINING_DONE", flush=True)
PY
)"

echo "started $NAME — logs: docker logs -f $NAME"
