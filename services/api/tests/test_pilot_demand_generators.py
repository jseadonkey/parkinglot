from __future__ import annotations

from pathlib import Path

from parking_core.pilot import load_pilot_config

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_load_pilot_merges_baltimore_demand_generators_file() -> None:
    pilot = load_pilot_config(REPO_ROOT / "config" / "pilot.yaml")
    names = {g["name"] for g in pilot.scoring.demand_generators}
    assert "Baltimore Penn Station" in names
    assert "Johns Hopkins Hospital — East Baltimore" in names
    assert "Phillips Seafood — Inner Harbor" in names
    assert "Target — Mondawmin" in names
    assert "Seattle downtown retail core" in names
    assert len(pilot.scoring.demand_generators) >= 70


def test_load_pilot_baltimore_profile() -> None:
    pilot = load_pilot_config(REPO_ROOT / "config" / "pilot_baltimore.yaml")
    names = {g["name"] for g in pilot.scoring.demand_generators}
    assert "Whole Foods — Harbor East" in names
    assert len(pilot.scoring.demand_generators) >= 70
    assert pilot.scoring.demand_generator_buffer_m == 450
