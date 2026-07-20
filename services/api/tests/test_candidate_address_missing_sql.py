"""Usable-street gap detection for WA/Baltimore address backfill targeting."""

from app.candidate_address import _missing_address_sql


def test_missing_address_sql_requires_usable_street_not_key_presence() -> None:
    sql = _missing_address_sql()
    # Must not treat "key exists" as enough — empty SITUS_ADDRESS is still missing.
    assert "raw_properties ?" not in sql
    assert "SITUS_ADDRESS" in sql
    assert "VISIT_ADDRESS" in sql
    # ZIP-only values are not usable streets.
    assert "^[0-9]{5}" in sql
