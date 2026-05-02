#!/usr/bin/env python3
"""Export a shortlist CSV for satellite / map visual review (scores + map URLs).

Requires ``DATABASE_URL`` and the API Python environment (same as
``export_scored_parcels_csv.py``). Prefer ``--limit`` with score floors to
produce a tractable subset after rule-based screening.

Examples:

  DATABASE_URL=postgresql+psycopg://... python3 scripts/parcel_visual_review_sheet.py -o review.csv

  python3 scripts/parcel_visual_review_sheet.py --limit 80 \\
    --min-score-identification 0.5 --min-score-entitlement 0.4 -o top.csv

In the API container (scripts copied to ``/app/scripts``; ``PYTHONPATH`` is set):

  docker compose exec api python /app/scripts/parcel_visual_review_sheet.py -o /tmp/review.csv

Or from a repo checkout on the host (mount / copy script if the image has no ``scripts/``).
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from parcel_export_common import build_scored_parcels_statement, ensure_api_path, normalize_database_url

# Washington — King County (parcel viewer is county-specific; other counties: use OSM/Google only).
KING_COUNTY_WA_FIPS = "53033"
KING_PARCEL_VIEWER_BASE = "https://gismaps.kingcounty.gov/parcelviewer2/"

# Lot-level satellite context
_MAP_ZOOM = 18


def _map_links(lat: object, lon: object, county_fips: str) -> tuple[str, str, str]:
    """Return (google, osm, king_viewer_or_empty). Empty strings if coordinates missing."""
    try:
        if lat is None or lon is None:
            return "", "", ""
        la = float(lat)
        lo = float(lon)
    except (TypeError, ValueError):
        return "", "", ""

    g = f"https://www.google.com/maps/@{la},{lo},{_MAP_ZOOM}z"
    osm = f"https://www.openstreetmap.org/?mlat={la}&mlon={lo}#map={_MAP_ZOOM}/{la}/{lo}"
    king = KING_PARCEL_VIEWER_BASE if (county_fips or "") == KING_COUNTY_WA_FIPS else ""
    return g, osm, king


def _fmt_cell(val: object) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Export parcels with latest identification / entitlement / strategic scores, "
            "centroids, and map URLs for visual site review."
        ),
    )
    p.add_argument(
        "--output",
        "-o",
        default="parcel_visual_review.csv",
        help="Output path (default: ./parcel_visual_review.csv). Use '-' for stdout.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of rows (after score filters).",
    )
    p.add_argument(
        "--min-score-identification",
        type=float,
        default=None,
        metavar="X",
        help="Keep rows with latest identification score >= X (excludes null scores).",
    )
    p.add_argument(
        "--min-score-entitlement",
        type=float,
        default=None,
        metavar="X",
        help="Keep rows with latest entitlement score >= X (excludes null scores).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not os.environ.get("DATABASE_URL", "").strip():
        print(
            "error: DATABASE_URL is not set.",
            file=sys.stderr,
        )
        return 2

    ensure_api_path()

    from sqlalchemy import create_engine

    url = normalize_database_url(os.environ["DATABASE_URL"].strip())
    engine = create_engine(url, pool_pre_ping=True)
    stmt = build_scored_parcels_statement(
        variant="visual_review",
        limit=args.limit,
        min_score_identification=args.min_score_identification,
        min_score_entitlement=args.min_score_entitlement,
    )

    fieldnames = (
        "parcel_id",
        "apn",
        "county_fips",
        "lot_sqft",
        "zoning_code",
        "zoning_allows_surface_parking",
        "score_identification",
        "score_entitlement",
        "score_strategic",
        "centroid_lat",
        "centroid_lon",
        "link_google_maps",
        "link_openstreetmap",
        "link_king_parcel_viewer",
    )

    out_path = args.output
    if out_path == "-":
        out_f = sys.stdout
        close_out = False
    else:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        out_f = path.open("w", newline="", encoding="utf-8")
        close_out = True

    try:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()
        with engine.connect() as conn:
            result = conn.execute(stmt)
            for row in result.mappings():
                lat, lon = row["centroid_lat"], row["centroid_lon"]
                g, osm, king = _map_links(lat, lon, str(row["county_fips"] or ""))
                writer.writerow(
                    {
                        "parcel_id": _fmt_cell(row["parcel_id"]),
                        "apn": _fmt_cell(row["apn"]),
                        "county_fips": _fmt_cell(row["county_fips"]),
                        "lot_sqft": _fmt_cell(row["lot_sqft"]),
                        "zoning_code": _fmt_cell(row["zoning_code"]),
                        "zoning_allows_surface_parking": _fmt_cell(row["zoning_allows_surface_parking"]),
                        "score_identification": _fmt_cell(row["score_identification"]),
                        "score_entitlement": _fmt_cell(row["score_entitlement"]),
                        "score_strategic": _fmt_cell(row["score_strategic"]),
                        "centroid_lat": _fmt_cell(lat),
                        "centroid_lon": _fmt_cell(lon),
                        "link_google_maps": g,
                        "link_openstreetmap": osm,
                        "link_king_parcel_viewer": king,
                    }
                )
    finally:
        if close_out:
            out_f.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
