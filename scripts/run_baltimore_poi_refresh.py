#!/usr/bin/env python3
"""Refresh OSM commercial POI counts for Baltimore City (no Celery).

  POI_LIMIT=50 MAX_BATCHES=20 python3 scripts/run_baltimore_poi_refresh.py

Each batch is rate-limited (~1 Overpass req/sec). Full city (~18k missing) takes hours.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
os.chdir(ROOT)

_env_file = ROOT / "deploy" / ".env"
if _env_file.is_file():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val

os.environ.setdefault("PILOT_CONFIG_PATH", str(ROOT / "config" / "pilot.yaml"))

from app.tasks import refresh_poi_density_batch  # noqa: E402

COUNTY = os.environ.get("BALTIMORE_COUNTY_FIPS", "24510")
BATCH = int(os.environ.get("POI_LIMIT", "50"))
MAX_BATCHES = int(os.environ.get("MAX_BATCHES", "0"))  # 0 = until no updates


def main() -> None:
    total = 0
    batch_n = 0
    while True:
        batch_n += 1
        if MAX_BATCHES and batch_n > MAX_BATCHES:
            print(f"stopped at MAX_BATCHES={MAX_BATCHES}", flush=True)
            break
        result = refresh_poi_density_batch(
            limit=BATCH,
            county_fips=COUNTY,
            only_missing=True,
        )
        updated = int(result.get("updated") or 0)
        errors = int(result.get("errors") or 0)
        total += updated
        print(f"batch {batch_n}: {result}", flush=True)
        if result.get("skipped"):
            break
        if updated == 0:
            print("no more missing POI counts", flush=True)
            break
    print(f"done — updated {total} parcels in {batch_n} batch(es)", flush=True)


if __name__ == "__main__":
    main()
