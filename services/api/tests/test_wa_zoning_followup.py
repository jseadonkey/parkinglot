from __future__ import annotations

import csv
from pathlib import Path

from app.wa_zoning_followup import build_zoning_followup_summary, summarize_county_zoning

FIELDS = [
    "state_fips",
    "county_fips",
    "county_name",
    "jurisdiction_type",
    "jurisdiction_id",
    "jurisdiction_name",
    "parent_county_fips",
    "zoning_authority_status",
    "address_source_status",
    "address_source_name",
    "value_source_status",
    "last_checked_at",
    "notes",
]


def _write_registry(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _row(county_fips: str, jurisdiction_id: str, zoning_status: str) -> dict[str, str]:
    return {
        "state_fips": "53",
        "county_fips": county_fips,
        "county_name": "Example",
        "jurisdiction_type": "countywide",
        "jurisdiction_id": jurisdiction_id,
        "jurisdiction_name": jurisdiction_id,
        "parent_county_fips": county_fips,
        "zoning_authority_status": zoning_status,
        "address_source_status": "not_started",
        "address_source_name": "",
        "value_source_status": "not_started",
        "last_checked_at": "2026-06-16",
        "notes": "",
    }


def test_loaded_county_with_not_started_zoning_needs_followup() -> None:
    out = summarize_county_zoning(
        county_fips="53063",
        parcels_in_db=100,
        registry_rows=[_row("53063", "spokane_county", "not_started")],
    )

    assert out["zoning_status"] == "needs_source_discovery"
    assert out["needs_followup"] is True
    assert "Find official zoning GIS" in out["next_action"]


def test_loaded_county_with_trusted_rows_is_not_followup() -> None:
    out = summarize_county_zoning(
        county_fips="53033",
        parcels_in_db=100,
        registry_rows=[
            _row("53033", "king_county", "qa_passed"),
            _row("53033", "king_unincorporated", "curated"),
        ],
    )

    assert out["zoning_status"] == "trusted"
    assert out["needs_followup"] is False


def test_followup_summary_orders_loaded_counties_by_rollout_priority(tmp_path: Path) -> None:
    registry = tmp_path / "registry.csv"
    _write_registry(
        registry,
        [
            _row("53033", "king_county", "qa_passed"),
            _row("53063", "spokane_county", "not_started"),
        ],
    )

    out = build_zoning_followup_summary(
        parcel_counts={"53063": 50, "53033": 100, "53005": 0},
        registry_path=registry,
        priority_order=["53033", "53005", "53063"],
    )

    assert out["loaded_counties"] == 2
    assert out["trusted_counties"] == 1
    assert out["followup_counties"] == 1
    assert out["next_county_needing_zoning"] == "53063"
    assert [row["county_fips"] for row in out["counties"]] == ["53033", "53063"]
