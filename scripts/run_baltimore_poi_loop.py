#!/usr/bin/env python3
"""Run multiple Baltimore POI refresh batches inline (no Celery).

  POI_BATCHES=5 POI_LIMIT=50 python3 scripts/run_baltimore_poi_loop.py
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
ROUNDS = int(os.environ.get("POI_BATCHES", "10"))


def main() -> None:
    for i in range(1, ROUNDS + 1):
        print(f"\n==> batch {i}/{ROUNDS}", flush=True)
        result = refresh_poi_density_batch(
            limit=BATCH,
            county_fips=COUNTY,
            only_missing=True,
            process_all=False,
        )
        print(result, flush=True)
        updated = int(result.get("updated") or 0)
        if updated == 0:
            print("no more parcels updated — done", flush=True)
            break


if __name__ == "__main__":
    main()
