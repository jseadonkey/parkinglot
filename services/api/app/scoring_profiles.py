"""Named score profiles for dual deterministic scorers (see config/pilot*.yaml)."""

from __future__ import annotations

from typing import Final, Literal

ENTITLEMENT: Final = "entitlement"
STRATEGIC: Final = "strategic"
# Written at GeoJSON ingest — prescreen from zoning/lot/demand signals available without full pipeline.
IDENTIFICATION: Final = "identification"

ScoreProfile = Literal["entitlement", "strategic", "identification"]

# Pipeline (`run_pipeline`) recomputes only these; identification is refreshed only on ingest.
PIPELINE_PROFILES: tuple[str, ...] = (ENTITLEMENT, STRATEGIC)

ALL_PROFILES: tuple[str, ...] = (ENTITLEMENT, STRATEGIC, IDENTIFICATION)

# Slack-facing labels
AGENT_ENTITLEMENT_NAME: Final = "Agent Atlas"
AGENT_ENTITLEMENT_TAGLINE: Final = "Entitlement & zoning (pilot.yaml)"

AGENT_STRATEGIC_NAME: Final = "Agent Beacon"
AGENT_STRATEGIC_TAGLINE: Final = "Strategic — demand & visibility (pilot_strategic.yaml)"

AGENT_IDENTIFICATION_NAME: Final = "Agent Cartographer"
AGENT_IDENTIFICATION_TAGLINE: Final = "Identification prescreen (pilot_identification.yaml)"
