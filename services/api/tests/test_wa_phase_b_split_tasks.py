"""Tests for split WA Phase B build/merge Celery tasks."""

from __future__ import annotations


def test_fetch_build_merge_skips_merge_when_validation_fails(monkeypatch) -> None:
    from app.tasks import fetch_build_merge_wa_county_zoning

    build_out = {
        "ok": False,
        "validation_failed": True,
        "county_fips": "53053",
        "reason": "overlay_coverage_below_minimum",
    }
    merge_calls: list = []

    monkeypatch.setattr(
        "app.tasks.build_county_zoning_overlay.run",
        lambda _cf: build_out,
    )
    monkeypatch.setattr(
        "app.tasks.merge_county_wa_zoning_overlay.run",
        lambda *a, **k: merge_calls.append((a, k)) or {"skipped": True},
    )

    out = fetch_build_merge_wa_county_zoning.run("53053")
    assert out["build"] == build_out
    assert out["merge"]["skipped"] is True
    assert merge_calls == []


def test_fetch_build_merge_runs_merge_after_successful_build(monkeypatch) -> None:
    from app.tasks import fetch_build_merge_wa_county_zoning

    build_out = {
        "ok": True,
        "county_fips": "53053",
        "overlay_path": "/app/data/pierce/pierce_county_zoning_overlay.geojson",
    }
    merge_out = {"county_fips": "53053", "merge": {"updated": 100}}

    monkeypatch.setattr("app.tasks.build_county_zoning_overlay.run", lambda _cf: build_out)
    monkeypatch.setattr(
        "app.tasks.merge_county_wa_zoning_overlay.run",
        lambda build, **kw: merge_out if build == build_out else {},
    )

    out = fetch_build_merge_wa_county_zoning.run("53053", max_pipeline=50)
    assert out["merge"] == merge_out


def test_merge_from_chain_skips_when_build_failed() -> None:
    from app.tasks import merge_county_wa_zoning_overlay

    out = merge_county_wa_zoning_overlay.run(
        {"ok": False, "validation_failed": True, "county_fips": "53053"},
    )
    assert out["skipped"] is True
    assert out["reason"] == "build_or_validation_failed"
