"""Pipeline funnel SQL helpers."""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from app.pipeline_funnel import (
    identification_prescreen_qualified,
    pipeline_funnel_backlog,
    ruled_out_by_prescreen,
)


def test_funnel_predicates_compile() -> None:
    dialect = postgresql.dialect()
    for expr in (
        identification_prescreen_qualified(45.0),
        pipeline_funnel_backlog(45.0),
        ruled_out_by_prescreen(45.0),
    ):
        compiled = str(expr.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
        assert "identification" in compiled.lower()
