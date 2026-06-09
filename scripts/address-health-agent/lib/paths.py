from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = REPO_ROOT / "data" / "jurisdictions" / "wa"
AGENT_DATA = REPO_ROOT / "data" / "operator-agent"
ROLLOUT_PLAN = DATA / "address_rollout_plan.yaml"
SOURCE_CHAINS = DATA / "address_source_chains.yaml"
SOURCE_CATALOG = DATA / "source_catalog.csv"
FIELD_MAPS = DATA / "address_field_maps.yaml"
STATE_FILE = AGENT_DATA / "address-health-state.json"
SNAPSHOT_FILE = AGENT_DATA / "address-health-snapshot.json"
