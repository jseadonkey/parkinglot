"""WorkflowRun ORM defaults + digest signal helpers (no DB required)."""

from __future__ import annotations

from app.db.models import WorkflowRun


def test_workflow_run_updated_at_has_onupdate() -> None:
    """ORM updates must bump updated_at so Slack digest queries see pipeline activity."""
    col = WorkflowRun.__table__.c.updated_at
    assert col.onupdate is not None
