"""Tests for repo-root discovery used by pilot scope boundary paths."""

from __future__ import annotations

from pathlib import Path

from parking_core.pilot_scope import _repo_relative, discover_repo_root

_REPO = Path(__file__).resolve().parents[3]


def test_repo_relative_finds_kent_boundary_in_dev_tree() -> None:
    p = _repo_relative(
        "data/boundaries/wa/kent_city_census_places.geojson",
        repo_root=_REPO,
    )
    assert p.is_file(), p


def test_discover_repo_root_from_pilot_config_path() -> None:
    root = discover_repo_root(pilot_config_path=_REPO / "config" / "pilot.yaml")
    assert root == _REPO


def test_repo_relative_prefers_app_data_mount(monkeypatch) -> None:
    seen: list[str] = []

    def fake_is_file(self: Path) -> bool:
        seen.append(str(self))
        return str(self) == "/app/data/boundaries/wa/kent_city_census_places.geojson"

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    resolved = _repo_relative(
        "data/boundaries/wa/kent_city_census_places.geojson",
        repo_root=Path("/usr/local/lib"),
    )
    assert str(resolved) == "/app/data/boundaries/wa/kent_city_census_places.geojson"
