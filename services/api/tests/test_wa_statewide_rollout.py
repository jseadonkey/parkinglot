from __future__ import annotations

from app.wa_statewide_rollout import county_priority_list, next_county_to_ingest


def test_county_priority_from_config() -> None:
    cfg = {"county_fips_priority": ["53033", "53053", "53061"]}
    assert county_priority_list(cfg, pilot_config_path="config/pilot.yaml") == ["53033", "53053", "53061"]


def test_county_priority_excludes_maryland_from_pilot_yaml() -> None:
    cfg: dict = {}
    priority = county_priority_list(cfg, pilot_config_path="config/pilot.yaml")
    assert "24510" not in priority
    assert "24005" not in priority
    assert all(f.startswith("53") for f in priority)


def test_next_county_skips_loaded(monkeypatch) -> None:
    cfg = {"county_fips_priority": ["53033", "53053", "53061"]}

    def fake_counts(_db, county_fips):
        return {"53033": 100_000, "53053": 0, "53061": 0}

    monkeypatch.setattr(
        "app.wa_statewide_rollout.parcel_counts_by_county",
        fake_counts,
    )
    assert next_county_to_ingest(None, config=cfg, pilot_config_path="config/pilot.yaml") == "53053"
