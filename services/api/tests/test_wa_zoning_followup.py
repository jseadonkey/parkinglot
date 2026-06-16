from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock

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


def test_ingest_hook_records_zoning_followup_for_loaded_wa_county(monkeypatch) -> None:
    from app import tasks

    audits: list[dict[str, object]] = []
    slack = MagicMock()

    monkeypatch.setattr(tasks, "get_settings", lambda: MagicMock(wa_jurisdiction_registry_path="registry.csv"))
    monkeypatch.setattr(tasks, "parcel_counts_by_county", lambda _db, counties: {counties[0]: 123})
    monkeypatch.setattr(
        tasks,
        "build_zoning_followup_summary",
        lambda **_kwargs: {
            "counties": [
                {
                    "county_fips": "53063",
                    "parcels_in_db": 123,
                    "zoning_status": "needs_source_discovery",
                    "needs_followup": True,
                    "jurisdiction_count": 3,
                    "jurisdiction_status_counts": {"not_started": 3},
                    "next_action": "Find official zoning GIS/use-table sources.",
                },
            ],
        },
    )
    monkeypatch.setattr(tasks, "post_agent_event_to_slack", slack)

    def fake_write_audit(_db, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(tasks, "write_audit", fake_write_audit)

    out = tasks._record_wa_zoning_followups_after_ingest(
        MagicMock(),
        county_touches={"53063": 10},
        source_path="/tmp/spokane.geojson",
    )

    assert [row["county_fips"] for row in out] == ["53063"]
    assert audits[0]["action"] == "wa_zoning_followup_required"
    assert audits[0]["entity_id"] == "53063"
    assert audits[0]["meta"]["parcels_touched_by_ingest"] == 10
    slack.assert_called_once()


def test_ingest_hook_ignores_non_wa_counties(monkeypatch) -> None:
    from app import tasks

    parcel_counts = MagicMock()
    monkeypatch.setattr(tasks, "parcel_counts_by_county", parcel_counts)

    out = tasks._record_wa_zoning_followups_after_ingest(
        MagicMock(),
        county_touches={"24510": 100},
        source_path="/tmp/baltimore.geojson",
    )

    assert out == []
    parcel_counts.assert_not_called()
