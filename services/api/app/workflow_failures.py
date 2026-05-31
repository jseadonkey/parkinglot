from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import WorkflowRun


def _error_signature(error: str | None) -> str:
    if not error:
        return "(no error text)"
    e = error.strip()
    if "NoSuchBucket" in e:
        return "NoSuchBucket (Spaces bucket missing or wrong name)"
    if len(e) > 100:
        return e[:100] + "…"
    return e


def workflow_failure_summary(
    db: Session,
    *,
    sample_per_group: int = 8,
    max_groups: int = 25,
) -> dict[str, Any]:
    """Aggregate failed workflow runs — mirrors Deal progress cards in operator console."""
    total_runs = db.scalar(select(func.count()).select_from(WorkflowRun)) or 0
    failed_count = (
        db.scalar(
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.status == "failed")
        )
        or 0
    )
    blocked_count = (
        db.scalar(
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.status == "blocked")
        )
        or 0
    )
    with_error_count = (
        db.scalar(
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.error.isnot(None))
        )
        or 0
    )

    failed_rows = list(
        db.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.status == "failed")
            .order_by(WorkflowRun.updated_at.desc())
        )
    )

    groups: dict[tuple[str | None, str], dict[str, Any]] = {}
    for row in failed_rows:
        step = row.current_step or "—"
        sig = _error_signature(row.error)
        key = (step, sig)
        if key not in groups:
            groups[key] = {
                "current_step": step,
                "error_signature": sig,
                "error_example": (row.error or "")[:240],
                "count": 0,
                "last_updated": row.updated_at,
                "sample_parcel_ids": [],
                "sample_run_ids": [],
            }
        g = groups[key]
        g["count"] += 1
        if row.updated_at and (g["last_updated"] is None or row.updated_at > g["last_updated"]):
            g["last_updated"] = row.updated_at
        if len(g["sample_parcel_ids"]) < sample_per_group:
            g["sample_parcel_ids"].append(str(row.parcel_id))
            g["sample_run_ids"].append(str(row.id))

    grouped = sorted(groups.values(), key=lambda x: (-x["count"], str(x["last_updated"] or "")))
    grouped = grouped[:max_groups]

    by_step: dict[str, int] = defaultdict(int)
    for row in failed_rows:
        by_step[row.current_step or "—"] += 1

    return {
        "total_runs": int(total_runs),
        "failed_count": int(failed_count),
        "blocked_count": int(blocked_count),
        "with_error_count": int(with_error_count),
        "ui_list_cap": 200,
        "ui_note": "Deal progress page only loads the latest 200 runs; use this endpoint for full failure counts.",
        "failed_by_step": dict(sorted(by_step.items(), key=lambda kv: -kv[1])),
        "failure_groups": grouped,
    }
