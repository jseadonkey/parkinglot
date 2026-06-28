"""Pipeline funnel SQL helpers."""

from __future__ import annotations

import uuid

from sqlalchemy.dialects import postgresql

from app.pipeline_funnel import (
    identification_prescreen_qualified,
    needs_pipeline_scoring,
    owner_outreach_target,
    pipeline_funnel_backlog,
    ruled_out_at_atlas,
    ruled_out_by_prescreen,
)


def test_funnel_predicates_compile() -> None:
    dialect = postgresql.dialect()
    for expr in (
        identification_prescreen_qualified(60.0),
        needs_pipeline_scoring(),
        pipeline_funnel_backlog(60.0),
        owner_outreach_target(entitlement_floor=85.0, strategic_floor=80.0),
        ruled_out_by_prescreen(60.0),
        ruled_out_at_atlas(),
    ):
        compiled = str(expr.compile(dialect=dialect, compile_kwargs={"literal_binds": True})).lower()
        assert "parcel_scores" in compiled
        assert "entitlement" in compiled or "identification" in compiled or "strategic" in compiled


def test_filter_prescreen_qualified_ids_chunks_large_in_lists(monkeypatch) -> None:
    from app.pipeline_funnel import PG_IN_LIST_CHUNK_SIZE, filter_prescreen_qualified_ids

    calls: list[int] = []

    def _fake_scores(_db, uuids, *, floor: float):
        calls.append(len(uuids))
        return [(str(uuids[0]), 70.0)] if uuids else []

    monkeypatch.setattr("app.pipeline_funnel._latest_identification_scores_for_ids", _fake_scores)
    monkeypatch.setattr("app.pipeline_funnel.identification_prescreen_floor", lambda: 60.0)

    n = PG_IN_LIST_CHUNK_SIZE + 500
    ids = [str(uuid.uuid4()) for _ in range(n)]
    out = filter_prescreen_qualified_ids(None, ids, limit=1)

    assert len(out) == 1
    assert len(calls) == 2
    assert calls[0] == PG_IN_LIST_CHUNK_SIZE
    assert calls[1] == 500
    compiled = str(
        owner_outreach_target(entitlement_floor=85.0, strategic_floor=80.0).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert "entitlement" in compiled
    assert "strategic" in compiled
    assert ">= 85.0" in compiled
    assert ">= 80.0" in compiled
