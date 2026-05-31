"""Tests for WA SOS registry lookup helpers."""

from __future__ import annotations

from parking_core.models import OwnerKind
from parking_enrichment.registry_lookup import lookup_secretary_of_state, registry_principals_as_persons


def test_lookup_disabled_returns_manual_url() -> None:
    row = lookup_secretary_of_state(
        enabled=False,
        county_fips="53033",
        owner_kind=OwnerKind.entity,
        query_name="ILLUFA LLC",
    )
    assert row is not None
    assert row.outcome == "manual_url_only"
    assert "ccfs.sos.wa.gov" in (row.search_results_url or "")


def test_registry_principals_as_persons_includes_agent_and_governors() -> None:
    registry = {
        "provider": "wa_sos_ccfs",
        "registered_agent_line": "PIE RUH LU",
        "registered_agent_address": "519 ROSARIO AVE NE, RENTON, WA",
        "principals": [{"name": "JANE DOE", "role": "GOVERNINGPERSON", "address": "123 MAIN ST"}],
    }
    persons = registry_principals_as_persons(registry)
    assert len(persons) == 2
    assert persons[0]["role"] == "registered_agent"
    assert persons[1]["name"] == "JANE DOE"
