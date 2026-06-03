#!/usr/bin/env python3
"""Run Baltimore demand-distance refresh + entitlement rescore synchronously (no Celery).

Use when Celery tasks stay PENDING or for one-shot ops from a machine with DATABASE_URL.

  python3 scripts/run_baltimore_demand_rescore.py
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
os.environ.setdefault("PILOT_IDENTIFICATION_CONFIG_PATH", str(ROOT / "config" / "pilot_identification.yaml"))
os.environ.setdefault("PILOT_STRATEGIC_CONFIG_PATH", str(ROOT / "config" / "pilot_strategic.yaml"))

from app.config import get_settings  # noqa: E402
from app.tasks import (  # noqa: E402
    refresh_demand_distances_batch,
    refresh_entitlement_scores_batch,
)

COUNTY = os.environ.get("BALTIMORE_COUNTY_FIPS", "24510")
CHUNK = int(os.environ.get("RESCORE_CHUNK", "2000"))


def main() -> None:
    settings = get_settings()
    print("database:", settings.database_url[:40] + "...")
    print("pilot:", settings.pilot_config_path)
    print("county:", COUNTY, "chunk:", CHUNK)

    print("\n==> refresh_demand_distances_batch (process_all, skip identification)", flush=True)
    demand = refresh_demand_distances_batch(
        limit=CHUNK,
        county_fips=COUNTY,
        process_all=True,
        refresh_identification=False,
    )
    print(demand, flush=True)

    print("\n==> refresh_entitlement_scores_batch (process_all)", flush=True)
    ent = refresh_entitlement_scores_batch(
        limit=CHUNK,
        county_fips=COUNTY,
        process_all=True,
    )
    print(ent, flush=True)


if __name__ == "__main__":
    main()
