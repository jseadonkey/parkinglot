from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from app.outreach_contacts import load_outreach_attempts, load_persisted_contact_points


def test_load_persisted_contact_points_when_table_missing() -> None:
    db = MagicMock()
    with patch("app.db.schema_compat.table_exists", return_value=False):
        rows = load_persisted_contact_points(db, uuid.uuid4())
    assert rows == []


def test_load_outreach_attempts_when_table_missing() -> None:
    db = MagicMock()
    with patch("app.db.schema_compat.table_exists", return_value=False):
        rows = load_outreach_attempts(db, uuid.uuid4())
    assert rows == []
