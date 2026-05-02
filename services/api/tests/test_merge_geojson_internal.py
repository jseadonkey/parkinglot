"""Merge overlay endpoint wires Celery task and returns task_id."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("APP_VERSION", "test")

from app.main import app  # noqa: E402


@patch("app.routers.internal.merge_parcel_attributes_geojson")
def test_merge_geojson_attributes_returns_task_id(mock_merge: MagicMock) -> None:
    mock_merge.delay.return_value = MagicMock(id="merge-task-test-id")
    client = TestClient(app)
    resp = client.post(
        "/internal/ingest/merge-geojson-attributes",
        json={
            "path": "/app/data/zoning/wa/overlay.geojson",
            "refresh_pipeline": True,
            "max_pipeline": 50,
            "delete_after": False,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == "merge-task-test-id"
    mock_merge.delay.assert_called_once()
    call_kw = mock_merge.delay.call_args
    assert call_kw[0][0] == "/app/data/zoning/wa/overlay.geojson"
