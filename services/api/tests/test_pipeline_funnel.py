"""Pipeline funnel SQL helpers."""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from app.pipeline_funnel import (
    identification_prescreen_qualified,
    needs_pipeline_scoring,
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
        ruled_out_by_prescreen(60.0),
        ruled_out_at_atlas(),
    ):
        compiled = str(expr.compile(dialect=dialect, compile_kwargs={"literal_binds": True})).lower()
        assert "parcel_scores" in compiled
        assert "entitlement" in compiled or "identification" in compiled or "strategic" in compiled
