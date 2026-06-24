from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def _page(apn: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"PARCEL_ID_NR": apn, "COUNTY_FIPS": "53005"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-119.3, 46.2],
                            [-119.3, 46.21],
                            [-119.29, 46.21],
                            [-119.29, 46.2],
                            [-119.3, 46.2],
                        ],
                    ],
                },
            },
        ],
    }


def test_fetch_watech_county_ingests_pages_and_records_completion(monkeypatch) -> None:
    import parking_ingestion.watech_parcels as watech
    from app import tasks

    audits: list[dict] = []

    def fake_pages(*_args, **_kwargs):
        yield _page("benton-1")
        yield _page("benton-2")

    def fake_ingest(path, **kwargs):
        assert kwargs["default_county_fips"] == "53005"
        assert kwargs["delete_after"] is True
        Path(path).unlink(missing_ok=True)
        return {
            "parcel_ids": [f"pid-{Path(path).stem}"],
            "inserted": 1,
            "updated": 0,
            "skipped": 0,
            "pipelines_enqueued": 1 if kwargs["max_auto_pipeline"] > 0 else 0,
        }

    monkeypatch.setattr(watech, "iter_county_geojson_pages", fake_pages)
    monkeypatch.setattr(tasks.ingest_geojson_path, "run", fake_ingest)
    monkeypatch.setattr(tasks, "_session", lambda: MagicMock())
    monkeypatch.setattr(tasks, "write_audit", lambda _db, **kwargs: audits.append(kwargs))

    result = tasks.fetch_watech_county_and_ingest.run(
        "53005",
        max_features=None,
        auto_run_pipeline=True,
        max_auto_pipeline=1,
    )

    assert result["parcel_features"] == 2
    assert result["pages_ingested"] == 2
    assert result["inserted"] == 2
    assert result["pipelines_enqueued"] == 1
    assert audits[-1]["action"] == "wa_statewide_county_ingest_completed"
    assert audits[-1]["entity_id"] == "53005"
    assert audits[-1]["meta"]["pages_ingested"] == 2
    assert audits[-1]["meta"]["inserted"] == 2


def test_fetch_watech_county_records_no_features_completion(monkeypatch) -> None:
    import parking_ingestion.watech_parcels as watech
    from app import tasks

    audits: list[dict] = []
    monkeypatch.setattr(watech, "iter_county_geojson_pages", lambda *_args, **_kwargs: iter(()))
    monkeypatch.setattr(tasks, "_session", lambda: MagicMock())
    monkeypatch.setattr(tasks, "write_audit", lambda _db, **kwargs: audits.append(kwargs))

    result = tasks.fetch_watech_county_and_ingest.run("53005")

    assert result["parcel_features"] == 0
    assert result["warning"]
    assert audits[-1]["action"] == "wa_statewide_county_ingest_completed"
    assert audits[-1]["meta"]["parcel_features"] == 0
    assert audits[-1]["meta"]["warning"] == result["warning"]
