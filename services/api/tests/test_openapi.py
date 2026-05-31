from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _schema_ref200(paths: dict, path: str, method: str) -> dict:
    return paths[path][method]["responses"]["200"]["content"]["application/json"]["schema"]


def test_openapi_lists_required_paths_and_response_models() -> None:
    """Ensure OpenAPI lists core routes and each successful JSON response uses a named schema."""
    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    paths: dict = spec["paths"]
    schemas: dict = spec.get("components", {}).get("schemas", {})

    required_paths = frozenset(
        {
            "/workflow-runs",
            "/workflow-runs/{run_id}",
            "/internal/tasks/{task_id}",
            "/internal/slack/digest-now",
            "/internal/slack/qualified-parcels-now",
            "/internal/slack/agent-discussion-preview",
            "/internal/slack/agent-discussion-now",
            "/internal/slack/status",
            "/internal/slack/digest-preview",
            "/internal/slack/test-message",
            "/internal/slack/full-update-now",
            "/internal/stats/scoring-summary",
            "/internal/stats/ingest-status",
            "/internal/stats/export-readiness",
            "/internal/stats/workflow-failures",
            "/internal/metrics/refresh-demand-distances",
            "/internal/metrics/refresh-identification-scores",
            "/internal/ingest/merge-geojson-attributes",
            "/internal/owners/peers-by-key",
            "/internal/owners/portfolios-ranked",
            "/internal/ingest/sample",
            "/internal/ingest/geojson-upload",
            "/internal/ingest/geojson-server-path",
            "/internal/ingest/watech-county",
            "/internal/pipeline/enqueue-unscored",
            "/internal/pipeline/enqueue-incomplete",
            "/internal/pipeline/outreach-board",
            "/internal/pipeline/deal-progress",
            "/parcels/{parcel_id}/workflow-runs",
            "/parcels/{parcel_id}/detail",
            "/parcels/{parcel_id}/pipeline/run",
            "/health",
            "/ready",
            "/parcels",
            "/parcels/{parcel_id}",
            "/parcels/{parcel_id}/score",
            "/approvals",
            "/approvals/{approval_id}/approve",
            "/approvals/{approval_id}/reject",
            "/audit",
        }
    )
    missing = required_paths - frozenset(paths)
    assert not missing, f"OpenAPI missing paths: {sorted(missing)}"

    object_refs: list[tuple[str, str, str]] = [
        ("/internal/tasks/{task_id}", "get", "CeleryTaskStatusResponse"),
        ("/internal/slack/status", "get", "SlackConfigStatusResponse"),
        ("/internal/stats/export-readiness", "get", "ExportReadinessResponse"),
        ("/internal/stats/scoring-summary", "get", "ScoringSummaryResponse"),
        ("/internal/stats/ingest-status", "get", "IngestStatusResponse"),
        ("/internal/stats/workflow-failures", "get", "WorkflowFailuresResponse"),
        ("/internal/slack/digest-preview", "get", "SlackDigestPreviewResponse"),
        ("/internal/slack/agent-discussion-preview", "get", "SlackAgentDiscussionPreviewResponse"),
        ("/internal/owners/peers-by-key", "get", "OwnersPeersByKeyResponse"),
        ("/internal/owners/portfolios-ranked", "get", "OwnersPortfoliosRankedResponse"),
        ("/internal/pipeline/outreach-board", "get", "OutreachPipelineBoardResponse"),
        ("/internal/pipeline/deal-progress", "get", "DealProgressBoardResponse"),
        ("/internal/slack/digest-now", "post", "CeleryTaskIdResponse"),
        ("/internal/slack/qualified-parcels-now", "post", "CeleryTaskIdResponse"),
        ("/internal/slack/agent-discussion-now", "post", "CeleryTaskIdResponse"),
        ("/internal/slack/full-update-now", "post", "FullSlackUpdateResponse"),
        ("/internal/slack/test-message", "post", "SlackTestMessagePostResponse"),
        ("/internal/ingest/sample", "post", "IngestSampleQueuedResponse"),
        ("/internal/ingest/geojson-upload", "post", "IngestGeojsonUploadQueuedResponse"),
        ("/internal/ingest/geojson-server-path", "post", "IngestGeojsonPathQueuedResponse"),
        ("/internal/ingest/watech-county", "post", "WaTechCountyQueuedResponse"),
        ("/internal/pipeline/enqueue-unscored", "post", "EnqueueUnscoredResponse"),
        ("/internal/pipeline/enqueue-incomplete", "post", "EnqueueIncompleteResponse"),
        ("/internal/ingest/merge-geojson-attributes", "post", "CeleryTaskIdResponse"),
        ("/internal/metrics/refresh-demand-distances", "post", "CeleryTaskIdResponse"),
        ("/internal/metrics/refresh-identification-scores", "post", "CeleryTaskIdResponse"),
        ("/health", "get", "ServiceStatusResponse"),
        ("/ready", "get", "ServiceStatusResponse"),
        ("/parcels/{parcel_id}/pipeline/run", "post", "ParcelPipelineTaskResponse"),
        ("/workflow-runs/{run_id}", "get", "WorkflowRunRead"),
        ("/parcels/{parcel_id}", "get", "ParcelRead"),
        ("/parcels/{parcel_id}/detail", "get", "ParcelDetailRead"),
        ("/parcels/{parcel_id}/score", "get", "ParcelScoreRead"),
        ("/approvals/{approval_id}/approve", "post", "ApprovalRead"),
        ("/approvals/{approval_id}/reject", "post", "ApprovalRead"),
    ]

    for path, method, name in object_refs:
        schema = _schema_ref200(paths, path, method)
        ref = schema.get("$ref")
        assert ref == f"#/components/schemas/{name}", (path, method, ref)
        assert name in schemas, (path, name)

    array_item_refs: list[tuple[str, str, str]] = [
        ("/workflow-runs", "get", "WorkflowRunRead"),
        ("/parcels", "get", "ParcelListRead"),
        ("/parcels/{parcel_id}/workflow-runs", "get", "WorkflowRunRead"),
        ("/approvals", "get", "ApprovalRead"),
        ("/audit", "get", "AuditRead"),
    ]

    for path, method, item in array_item_refs:
        schema = _schema_ref200(paths, path, method)
        assert schema.get("type") == "array", (path, method, schema)
        ref = schema["items"].get("$ref")
        assert ref == f"#/components/schemas/{item}", (path, method, ref)
        assert item in schemas, (path, item)

    # Nested models used by owner portfolio responses (documented via parents)
    for nested in ("PeerParcelSummary", "OwnerPortfolioRankRow"):
        assert nested in schemas
