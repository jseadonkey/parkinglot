#!/usr/bin/env python3
"""Stream WaTech King County parcels through the pilot pre-ingest funnel.

Funnel: geography (Kent + unincorporated King) → land use → min lot size → optional zoning.

  cd /opt/workspaces/parkinglot
  set -a && source deploy/.env && set +a
  export KENT_ZONING KING_ZONING   # optional; see docs/zoning-sources-kent.md

  .venv/bin/python scripts/fetch_pilot_parcel_candidates.py \\
    -o data/pilot/kent_pilot_candidates.geojson

  .venv/bin/python scripts/fetch_pilot_parcel_candidates.py --stats-only --max-scan 50000
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _ensure_paths() -> None:
    for rel in ("services/ingestion", "packages/core"):
        p = _REPO / rel
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


def main() -> int:
    _ensure_paths()

    from parking_ingestion.pilot_prescreen import (
        PilotParcelPrescreener,
        PrescreenStats,
        load_prescreen_config,
    )
    from parking_ingestion.pilot_zoning_index import PilotZoningLookup
    from parking_ingestion.watech_parcels import iterate_county_features

    parser = argparse.ArgumentParser(description="Fetch + prescreen Kent pilot parcel candidates from WaTech.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_REPO / "data/pilot/kent_pilot_candidates.geojson",
        help="Output GeoJSON path",
    )
    parser.add_argument(
        "--county-fips",
        default="53033",
        help="Washington county FIPS (default King)",
    )
    parser.add_argument(
        "--pilot-config",
        type=Path,
        default=_REPO / "config/pilot.yaml",
    )
    parser.add_argument(
        "--prescreen-config",
        type=Path,
        default=_REPO / "config/pilot_parcel_prescreen.yaml",
    )
    parser.add_argument(
        "--max-scan",
        type=int,
        default=None,
        help="Stop after scanning N WaTech rows (debug / stats)",
    )
    parser.add_argument(
        "--max-kept",
        type=int,
        default=None,
        help="Stop after keeping N candidates",
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Print funnel stats JSON only; do not write output file",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=2000,
    )
    args = parser.parse_args()

    prescreen = load_prescreen_config(args.prescreen_config)
    if prescreen.zoning_enabled and prescreen.zoning_mode != "off":
        zoning_lookup = PilotZoningLookup.from_env()
        if zoning_lookup is None:
            print(
                "warning: KENT_ZONING / KING_ZONING not set — zoning codes will be omitted; "
                "land-use + geography filters still apply.",
                file=sys.stderr,
            )
    else:
        zoning_lookup = None

    prescreener = PilotParcelPrescreener(
        pilot_config_path=args.pilot_config,
        prescreen=prescreen,
        zoning_lookup=zoning_lookup,
    )

    stats = PrescreenStats()
    kept_features: list[dict] = []

    print(
        f"Scanning WaTech county {args.county_fips} "
        f"(geography + land use + min {prescreen.min_sqft:.0f} sqft)…",
        flush=True,
    )

    for feat in iterate_county_features(
        args.county_fips,
        page_size=args.page_size,
        max_features=args.max_scan,
    ):
        stats.scanned += 1
        keep, props, reason = prescreener.evaluate_feature(feat)
        if not keep:
            if reason in ("no_geometry", "bad_geometry", "empty_geometry"):
                stats.rejected_no_geometry += 1
            elif reason == "geography":
                stats.rejected_geography += 1
            elif reason == "land_use":
                stats.rejected_land_use += 1
            elif reason == "lot_size":
                stats.rejected_lot_size += 1
            elif reason == "zoning":
                stats.rejected_zoning += 1
        else:
            stats.kept += 1
            juris = (props or {}).get("ZONING_JURISDICTION")
            if juris == "kent_city":
                stats.kent_city += 1
            elif juris == "king_unincorporated":
                stats.king_unincorporated += 1
            if not args.stats_only:
                kept_features.append(
                    {
                        "type": "Feature",
                        "geometry": feat["geometry"],
                        "properties": props,
                    }
                )
            if args.max_kept is not None and stats.kept >= args.max_kept:
                break

        if stats.scanned % 10000 == 0:
            print(
                f"  scanned {stats.scanned:,} — kept {stats.kept:,} "
                f"(geo reject {stats.rejected_geography:,})",
                flush=True,
            )

    summary = {
        **asdict(stats),
        "county_fips": args.county_fips,
        "output": None if args.stats_only else str(args.output.resolve()),
    }
    print(json.dumps(summary, indent=2))

    if args.stats_only:
        return 0

    if stats.kept == 0:
        print("error: no candidates passed the funnel", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", "features": kept_features}
    args.output.write_text(json.dumps(fc), encoding="utf-8")
    print(f"Wrote {stats.kept:,} features to {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
