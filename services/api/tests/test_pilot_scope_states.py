from __future__ import annotations

from app.pilot_scope import states_in_scope_from_fips


def test_states_in_scope_maryland_and_washington() -> None:
    fips = ["24510", "24005", "53033", "53053"]
    states = states_in_scope_from_fips(fips)
    assert len(states) == 2
    assert states[0]["state_fips"] == "24"
    assert states[0]["county_count"] == 2
    assert states[1]["state_fips"] == "53"
    assert states[1]["county_count"] == 2
