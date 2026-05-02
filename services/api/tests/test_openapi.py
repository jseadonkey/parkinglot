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
    assert "/internal/stats/export-readiness" in paths
    assert "/internal/metrics/refresh-demand-distances" in paths
    assert "/internal/metrics/refresh-identification-scores" in paths
    assert "/internal/ingest/merge-geojson-attributes" in paths
    assert "/internal/owners/peers-by-key" in paths
    assert "/internal/owners/portfolios-ranked" in paths
    schemas = spec.get("components", {}).get("schemas", {})
    assert "PeerParcelSummary" in schemas
    assert "OwnersPeersByKeyResponse" in schemas
    assert "OwnerPortfolioRankRow" in schemas
    assert "OwnersPortfoliosRankedResponse" in schemas
    peers_get = paths["/internal/owners/peers-by-key"]["get"]
    assert peers_get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/OwnersPeersByKeyResponse"
    )
    ranked_get = paths["/internal/owners/portfolios-ranked"]["get"]
    assert ranked_get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/OwnersPortfoliosRankedResponse"
    )
    assert "/internal/ingest/sample" in paths
    assert "/internal/ingest/geojson-upload" in paths
    assert "/internal/ingest/geojson-server-path" in paths
    assert "/internal/ingest/watech-county" in paths
    assert "/internal/pipeline/enqueue-unscored" in paths
    assert "/internal/pipeline/enqueue-incomplete" in paths
    assert "/parcels/{parcel_id}/workflow-runs" in paths
