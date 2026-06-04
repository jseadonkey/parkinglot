"""Deal progress board query."""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from app.deal_progress import query_deal_progress_board


def test_deal_progress_state_filter_compiles() -> None:
    """Geo filter applies in SQL (not only after a global scan cap)."""
    dialect = postgresql.dialect()

    class _FakeResult:
        def __init__(self, rows: list) -> None:
            self._rows = rows

        def all(self) -> list:
            return self._rows

    class _FakeSession:
        def execute(self, stmt):  # noqa: ANN001
            compiled = str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True})).lower()
            assert "24510" not in compiled
            assert "county_fips like '24'" in compiled
            return _FakeResult([])

    summary, rows = query_deal_progress_board(_FakeSession(), limit=100, state_fips="24")
    assert summary.total_parcels == 0
    assert rows == []
