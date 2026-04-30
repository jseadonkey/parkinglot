Workflow **status and steps** live in `parking_workflows.state`. Celery task orchestration is implemented in [`services/api/app/tasks.py`](../api/app/tasks.py) (`run_pipeline`, `ingest_geojson_path`). Human blocking states are represented by `workflow_runs.status=blocked` and pending rows in `approval_requests`.

**HTTP visibility:** `GET /workflow-runs`, `GET /workflow-runs/{run_id}`, and `GET /parcels/{parcel_id}/workflow-runs` on the API; Celery state via `GET /internal/tasks/{task_id}` (see [`docs/OPERATIONS.md`](../../docs/OPERATIONS.md)).
