from __future__ import annotations

from unittest.mock import MagicMock

from app.scoring_summary import (
    _count_paired_latest_ent_strategic,
    _count_subquery_qualified,
    _count_subquery_rows,
    _latest_scores_subquery,
)


def test_latest_scores_subquery_builds() -> None:
    subq = _latest_scores_subquery("entitlement")
    assert subq.c.parcel_id is not None
    assert subq.c.total_score is not None


def test_count_helpers_use_scalar() -> None:
    db = MagicMock()
    db.scalar.return_value = 42
    subq = _latest_scores_subquery("entitlement")
    assert _count_subquery_rows(db, subq) == 42
    assert _count_subquery_qualified(db, subq, 55.0) == 42
    db.scalar.return_value = 7
    assert _count_paired_latest_ent_strategic(db) == 7
