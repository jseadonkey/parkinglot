"""When to compute parking comp metrics (entitlement + zoning + building gates)."""

from __future__ import annotations

from app.db.models import Parcel
from parking_core.pilot import PilotConfig
from parking_ingestion.building_prescreen import building_value_prescreen_pass


def parcel_meets_parking_comp_gate(
    parcel: Parcel,
    entitlement_score: float,
    pilot_ent: PilotConfig,
    *,
    max_building_share: float = 0.70,
    require_surface_zoning: bool = True,
) -> bool:
    """True when comp lookup + strategic comp scoring is worth running."""
    floor = float(pilot_ent.scoring.qualified_min_score)
    if entitlement_score < floor:
        return False
    if require_surface_zoning and not parcel.zoning_allows_surface_parking:
        return False
    raw = parcel.raw_properties if isinstance(parcel.raw_properties, dict) else {}
    return building_value_prescreen_pass(raw, max_building_share=max_building_share)
