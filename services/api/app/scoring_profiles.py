"""Named score profiles for dual deterministic scorers (see config/pilot*.yaml)."""

from __future__ import annotations

from typing import Final, Literal

ENTITLEMENT: Final = "entitlement"
STRATEGIC: Final = "strategic"

ScoreProfile = Literal["entitlement", "strategic"]

# Slack-facing labels
AGENT_ENTITLEMENT_NAME: Final = "Agent Atlas"
AGENT_ENTITLEMENT_TAGLINE: Final = "Entitlement & zoning (pilot.yaml)"

AGENT_STRATEGIC_NAME: Final = "Agent Beacon"
AGENT_STRATEGIC_TAGLINE: Final = "Strategic — demand & visibility (pilot_strategic.yaml)"

ALL_PROFILES: tuple[str, ...] = (ENTITLEMENT, STRATEGIC)
