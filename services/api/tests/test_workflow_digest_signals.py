"""WorkflowRun ORM defaults + digest signal helpers (no DB required)."""

from __future__ import annotations

from app.config import Settings
from app.db.models import WorkflowRun


def test_scheduled_enqueue_unscored_defaults() -> None:
    """Periodic backlog drain is on by default so production makes scoring progress without manual POSTs."""
    s = Settings()
    assert s.scheduled_enqueue_unscored_enabled is True
    assert s.scheduled_enqueue_unscored_limit >= 1
    assert s.scheduled_enqueue_unscored_crontab_hour == "*/4"


def test_workflow_run_updated_at_has_onupdate() -> None:
    """ORM updates must bump updated_at so Slack digest queries see pipeline activity."""
    col = WorkflowRun.__table__.c.updated_at
    assert col.onupdate is not None
