from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.wa_statewide_rollout import (
    cooldown_days_after_county,
    county_priority_list,
    next_county_to_ingest,
    wa_rollout_pending_ingest_state,
)

_PILOT = str(Path(__file__).resolve().parents[3] / "config/pilot.yaml")


def test_county_priority_from_config() -> None:
    cfg = {"county_fips_priority": ["53033", "53053", "53061"]}
    assert county_priority_list(cfg, pilot_config_path=_PILOT) == ["53033", "53053", "53061"]


def test_county_priority_excludes_maryland_from_pilot_yaml() -> None:
    cfg: dict = {}
    priority = county_priority_list(cfg, pilot_config_path=_PILOT)
    assert "24510" not in priority
    assert "24005" not in priority
    assert all(f.startswith("53") for f in priority)


def test_cooldown_scales_with_parcel_count() -> None:
    cfg = {"min_days_base": 0.5, "min_days_per_10k_parcels": 0.75, "min_days_max": 10}
    assert cooldown_days_after_county(5_000, cfg) == 0.875
    assert cooldown_days_after_county(50_000, cfg) == 4.25
    assert cooldown_days_after_county(200_000, cfg) == 10.0


def test_cooldown_legacy_flat_week() -> None:
    assert cooldown_days_after_county(1_000, {"min_days_between_counties": 7}) == 7.0


def test_next_county_skips_loaded(monkeypatch) -> None:
    cfg = {"county_fips_priority": ["53033", "53053", "53061"]}

    def fake_counts(_db, county_fips):
        return {"53033": 100_000, "53053": 0, "53061": 0}

    monkeypatch.setattr(
        "app.wa_statewide_rollout.parcel_counts_by_county",
        fake_counts,
    )
    assert next_county_to_ingest(None, config=cfg, pilot_config_path=_PILOT) == "53053"


def test_pending_ingest_blocks_duplicate_zero_row_county(monkeypatch) -> None:
    class _Result:
        def scalar_one_or_none(self):
            return SimpleNamespace(
                action="wa_statewide_county_ingest",
                entity_id="53063",
                created_at=datetime.now(UTC) - timedelta(hours=2),
            )

    db = SimpleNamespace(execute=lambda *_args, **_kwargs: _Result())
    monkeypatch.setattr(
        "app.wa_statewide_rollout.parcel_counts_by_county",
        lambda _db, _county_fips: {"53063": 0},
    )

    out = wa_rollout_pending_ingest_state(db, {"pending_ingest_lock_days": 1.0})

    assert out["pending"] is True
    assert out["pending_county_fips"] == "53063"
    assert out["pending_age_days"] < 1.0


def test_pending_ingest_clears_after_rows_land(monkeypatch) -> None:
    class _Result:
        def scalar_one_or_none(self):
            return SimpleNamespace(
                action="wa_statewide_county_ingest",
                entity_id="53063",
                created_at=datetime.now(UTC) - timedelta(hours=2),
            )

    db = SimpleNamespace(execute=lambda *_args, **_kwargs: _Result())
    monkeypatch.setattr(
        "app.wa_statewide_rollout.parcel_counts_by_county",
        lambda _db, _county_fips: {"53063": 25},
    )

    out = wa_rollout_pending_ingest_state(db, {"pending_ingest_lock_days": 1.0})

    assert out["pending"] is False
    assert out["pending_county_fips"] is None
