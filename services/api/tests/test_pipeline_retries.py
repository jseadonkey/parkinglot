from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.pipeline_retries import enqueue_draft_storage_failure_reruns, is_draft_storage_bucket_error


def test_is_draft_storage_bucket_error_matches_nosuchbucket() -> None:
    assert is_draft_storage_bucket_error("botocore ClientError: NoSuchBucket")
    assert not is_draft_storage_bucket_error("timeout talking to vendor")
    assert not is_draft_storage_bucket_error(None)


def test_enqueue_draft_storage_failure_reruns_skips_rows_with_newer_runs() -> None:
    current_parcel_id = uuid.uuid4()
    stale_parcel_id = uuid.uuid4()
    failed_runs = [
        SimpleNamespace(
            id=uuid.uuid4(),
            parcel_id=current_parcel_id,
            created_at=datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            parcel_id=stale_parcel_id,
            created_at=datetime(2026, 6, 10, 13, 0, tzinfo=UTC),
        ),
    ]
    db = MagicMock()
    db.scalars.return_value = failed_runs
    db.scalar.side_effect = [None, uuid.uuid4()]

    with patch("app.pipeline_retries.run_pipeline.delay") as delay:
        delay.return_value = SimpleNamespace(id="task-1")
        out = enqueue_draft_storage_failure_reruns(db, limit=500)

    assert out["matched_failed_runs"] == 2
    assert out["enqueued"] == 1
    assert out["skipped_newer_run"] == 1
    assert out["parcel_ids"] == [str(current_parcel_id)]
    assert out["task_ids"] == ["task-1"]
    assert out["limit"] == 200
    delay.assert_called_once_with(str(current_parcel_id))
