from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import WorkflowRun
from app.tasks import run_pipeline
from parking_workflows.state import WorkflowStatus

DRAFT_STORAGE_BUCKET_ERROR_MARKER = "NoSuchBucket"


def is_draft_storage_bucket_error(error: str | None) -> bool:
    """Known recoverable failure from before the object-storage bucket existed."""
    return bool(error and DRAFT_STORAGE_BUCKET_ERROR_MARKER in error)


def enqueue_draft_storage_failure_reruns(db: Session, *, limit: int = 50) -> dict[str, Any]:
    """Rerun latest failed parcel pipelines caused by the now-fixed draft bucket.

    Older failed rows remain in the audit trail after a successful rerun. To avoid
    duplicate work, only enqueue a failed run when there is no newer workflow run
    for the same parcel.
    """
    cap = min(max(limit, 1), 200)
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.status == WorkflowStatus.failed.value)
        .where(WorkflowRun.error.ilike(f"%{DRAFT_STORAGE_BUCKET_ERROR_MARKER}%"))
        .order_by(WorkflowRun.updated_at.desc(), WorkflowRun.created_at.desc())
        .limit(cap)
    )
    failed_runs = list(db.scalars(stmt))
    parcel_ids: list[str] = []
    task_ids: list[str] = []
    skipped_newer_run = 0
    for failed_run in failed_runs:
        newer_stmt = (
            select(WorkflowRun.id)
            .where(WorkflowRun.parcel_id == failed_run.parcel_id)
            .where(WorkflowRun.created_at > failed_run.created_at)
            .limit(1)
        )
        if db.scalar(newer_stmt):
            skipped_newer_run += 1
            continue
        async_result = run_pipeline.delay(str(failed_run.parcel_id))
        parcel_ids.append(str(failed_run.parcel_id))
        task_ids.append(str(async_result.id))

    return {
        "matched_failed_runs": len(failed_runs),
        "enqueued": len(task_ids),
        "skipped_newer_run": skipped_newer_run,
        "parcel_ids": parcel_ids,
        "task_ids": task_ids,
        "limit": cap,
    }
