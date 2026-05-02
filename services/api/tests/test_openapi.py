from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_openapi_lists_workflow_and_internal_task_paths() -> None:
    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/workflow-runs" in paths
    assert "/workflow-runs/{run_id}" in paths
    assert "/internal/tasks/{task_id}" in paths
    assert "/internal/slack/digest-now" in paths
    assert "/internal/slack/qualified-parcels-now" in paths
    assert "/internal/slack/agent-discussion-preview" in paths
    assert "/internal/slack/agent-discussion-now" in paths
    assert "/internal/slack/status" in paths
    assert "/internal/slack/digest-preview" in paths
    assert "/internal/slack/test-message" in paths
    assert "/internal/slack/full-update-now" in paths
    assert "/internal/stats/scoring-summary" in paths
    assert "/internal/ingest/geojson-upload" in paths
    assert "/internal/ingest/geojson-server-path" in paths
    assert "/internal/pipeline/enqueue-unscored" in paths
    assert "/parcels/{parcel_id}/workflow-runs" in paths
