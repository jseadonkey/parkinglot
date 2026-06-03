#!/usr/bin/env python3
"""Refresh OSM commercial POI counts for Baltimore City (no Celery).

Safe alongside live workers: short per-parcel commits + deadlock retry in the API task.

  python3 scripts/run_baltimore_poi_refresh.py

Optional: POI_LIMIT=50 POI_PROCESS_ALL=false  (single chunk only)
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
PROCESS_ALL = os.environ.get("POI_PROCESS_ALL", "true").lower() in ("1", "true", "yes")


def main() -> None:
    result = refresh_poi_density_batch(
        limit=BATCH,
        county_fips=COUNTY,
        only_missing=True,
        process_all=PROCESS_ALL,
    )
    print(result, flush=True)


if __name__ == "__main__":
    main()
