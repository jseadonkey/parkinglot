"""Track zoning work that must follow WA parcel ingest."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

TRUSTED_ZONING_STATUSES = {"qa_passed", "curated"}
IN_PROGRESS_ZONING_STATUSES = {"source_found", "layer_downloaded", "joined", "rules_drafted", "in_review"}
BLOCKED_ZONING_STATUSES = {"blocked"}
DONE_OR_NOT_APPLICABLE_STATUSES = TRUSTED_ZONING_STATUSES | {"not_applicable"}


def resolve_registry_path(path: str | Path | None = None) -> Path:
    """Resolve the WA jurisdiction registry in local checkout or Docker image layouts."""
    raw = Path(str(path or "data/jurisdictions/wa/jurisdiction_registry.csv")).expanduser()
    if raw.is_absolute():
        return raw

    app_file = Path(__file__).resolve()
    candidates = [
        Path.cwd() / raw,
        app_file.parents[3] / raw,  # local repo: /workspace; Docker image: /app
        app_file.parents[1] / raw,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def read_registry_rows(path: str | Path | None = None) -> list[dict[str, str]]:
    registry_path = resolve_registry_path(path)
    if not registry_path.is_file():
        return []
    with registry_path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _status_for_rows(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "missing_registry"
    statuses = {(row.get("zoning_authority_status") or "not_started").strip() for row in rows}
    if statuses and statuses <= DONE_OR_NOT_APPLICABLE_STATUSES:
        return "trusted"
    if statuses & BLOCKED_ZONING_STATUSES:
        return "blocked"
    if statuses & IN_PROGRESS_ZONING_STATUSES:
        return "in_progress"
    return "needs_source_discovery"


def _next_action(status: str) -> str:
    return {
        "missing_registry": "Add countywide, unincorporated, and city jurisdiction rows before trusting zoning.",
        "needs_source_discovery": (
            "Find official zoning GIS/use-table sources for city and unincorporated jurisdictions, "
            "then record them in the WA registry/source catalog."
        ),
        "in_progress": "Finish zoning layer join, surface-parking rules draft, and QA review.",
        "blocked": "Pick an alternate public source or licensed zoning vendor and record the blocker.",
        "trusted": "No zoning follow-up needed for the currently registered jurisdictions.",
    }[status]


def summarize_county_zoning(
    *,
    county_fips: str,
    parcels_in_db: int,
    registry_rows: list[dict[str, str]],
) -> dict[str, Any]:
    county_rows = [
        row
        for row in registry_rows
        if (row.get("state_fips") or "").strip() == "53"
        and (row.get("county_fips") or "").strip() == county_fips
    ]
    counts = Counter((row.get("zoning_authority_status") or "not_started").strip() for row in county_rows)
    status = _status_for_rows(county_rows)
    needs_followup = parcels_in_db > 0 and status != "trusted"
    samples = [
        (row.get("jurisdiction_id") or "").strip()
        for row in county_rows
        if (row.get("jurisdiction_id") or "").strip()
    ][:8]
    return {
        "county_fips": county_fips,
        "parcels_in_db": parcels_in_db,
        "zoning_status": status,
        "needs_followup": needs_followup,
        "jurisdiction_count": len(county_rows),
        "jurisdiction_status_counts": dict(sorted(counts.items())),
        "sample_jurisdictions": samples,
        "next_action": _next_action(status),
    }


def build_zoning_followup_summary(
    *,
    parcel_counts: dict[str, int],
    registry_path: str | Path | None = None,
    priority_order: list[str] | None = None,
) -> dict[str, Any]:
    """Build a county-level zoning queue from live parcel counts plus registry status."""
    registry = read_registry_rows(registry_path)
    resolved = resolve_registry_path(registry_path)
    ordered = [str(f).strip() for f in (priority_order or []) if str(f).strip()]
    for fips in sorted(parcel_counts):
        if fips.startswith("53") and fips not in ordered:
            ordered.append(fips)

    counties = [
        summarize_county_zoning(
            county_fips=fips,
            parcels_in_db=int(parcel_counts.get(fips, 0) or 0),
            registry_rows=registry,
        )
        for fips in ordered
        if fips.startswith("53") and int(parcel_counts.get(fips, 0) or 0) > 0
    ]
    followup = [row for row in counties if row["needs_followup"]]
    trusted = [row for row in counties if row["zoning_status"] == "trusted"]
    blocked = [row for row in counties if row["zoning_status"] == "blocked"]
    return {
        "registry_path": str(resolved),
        "loaded_counties": len(counties),
        "trusted_counties": len(trusted),
        "followup_counties": len(followup),
        "blocked_counties": len(blocked),
        "counties": counties,
        "next_county_needing_zoning": followup[0]["county_fips"] if followup else None,
    }
