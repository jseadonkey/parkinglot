#!/usr/bin/env python3
"""Report WA counties where parcel ingest has created zoning follow-up work."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from app.wa_zoning_followup import build_zoning_followup_summary  # noqa: E402


def _load_rollout_status(path: Path) -> dict[str, int]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for row in raw.get("counties") or []:
        if not isinstance(row, dict):
            continue
        fips = str(row.get("county_fips") or "").strip()
        if fips:
            counts[fips] = int(row.get("parcels_in_db") or 0)
    return counts


def _parse_count_args(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--county-count must use FIPS=COUNT, got {value!r}")
        fips, count = value.split("=", 1)
        counts[fips.strip()] = int(count.strip())
    return counts


def _live_db_counts() -> dict[str, int] | None:
    if not (os.environ.get("DATABASE_URL") or "").strip():
        return None
    try:
        from app.config import get_settings
        from app.db.session import SessionLocal
        from app.wa_statewide_rollout import county_priority_list, load_rollout_config, parcel_counts_by_county

        settings = get_settings()
        rollout = load_rollout_config(settings.wa_statewide_rollout_config_path)
        priority = county_priority_list(rollout, pilot_config_path=settings.pilot_config_path)
        with SessionLocal() as db:
            return parcel_counts_by_county(db, priority)
    except Exception as exc:
        print(f"Live DB parcel counts unavailable: {exc}", file=sys.stderr)
        return None


def _print_text(report: dict[str, Any]) -> None:
    print("WA zoning follow-up")
    print(f"  loaded counties: {report['loaded_counties']}")
    print(f"  trusted zoning counties: {report['trusted_counties']}")
    print(f"  counties needing zoning follow-up: {report['followup_counties']}")
    nxt = report.get("next_county_needing_zoning")
    if nxt:
        print(f"  next zoning county: {nxt}")
    print(f"  registry: {report['registry_path']}")
    for row in report.get("counties") or []:
        marker = "TODO" if row.get("needs_followup") else "OK"
        counts = ", ".join(f"{k}={v}" for k, v in (row.get("jurisdiction_status_counts") or {}).items())
        print(
            f"  {marker} {row['county_fips']}: {row['parcels_in_db']:,} parcels, "
            f"zoning={row['zoning_status']}, jurisdictions={row['jurisdiction_count']}"
            + (f" ({counts})" if counts else "")
        )
        if row.get("needs_followup"):
            print(f"       next: {row['next_action']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Report WA parcel-loaded counties that still need zoning work.")
    parser.add_argument(
        "--registry",
        type=Path,
        default=REPO_ROOT / "data" / "jurisdictions" / "wa" / "jurisdiction_registry.csv",
    )
    parser.add_argument("--rollout-status-json", type=Path, help="JSON from /internal/ingest/wa-rollout-status")
    parser.add_argument(
        "--county-count",
        action="append",
        default=[],
        metavar="FIPS=COUNT",
        help="Parcel count override; may be repeated.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--fail-on-followup",
        action="store_true",
        help="Exit 2 when any loaded county still needs zoning follow-up.",
    )
    args = parser.parse_args()

    counts: dict[str, int] = {}
    if args.rollout_status_json:
        counts.update(_load_rollout_status(args.rollout_status_json))
    counts.update(_parse_count_args(args.county_count))
    if not counts:
        live_counts = _live_db_counts()
        if live_counts is not None:
            counts.update(live_counts)

    if not counts:
        print(
            "No parcel counts available. Provide --rollout-status-json, --county-count FIPS=COUNT, "
            "or run with DATABASE_URL set.",
            file=sys.stderr,
        )
        return 1

    report = build_zoning_followup_summary(parcel_counts=counts, registry_path=args.registry)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_text(report)

    if args.fail_on_followup and int(report.get("followup_counties") or 0) > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
