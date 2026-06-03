from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class RegionConfig(BaseModel):
    name: str
    state_fips: str
    county_fips: list[str] = Field(default_factory=list)
    primary_metro_cbsa: str | None = None


class DealOperationsConfig(BaseModel):
    """How we operate sites after land is under lease — see docs/OPERATIONS-MODEL.md."""

    model: str = "master_lease_then_sublease"
    our_role: str = "land_aggregator"
    partner_role: str = "parking_operator"
    landowner_agreement: str = "master_lease"
    partner_agreement: str = "sublease"
    use_class: str = "unmanned_surface_parking_primary"
    excludes: list[str] = Field(
        default_factory=lambda: [
            "attended_garage",
            "valet",
            "accessory_only_for_building",
        ]
    )
    partner_provides: list[str] = Field(
        default_factory=lambda: [
            "signage",
            "lpr_cameras",
            "payment_platform",
            "enforcement",
            "operating_capex",
        ]
    )


class DealConfig(BaseModel):
    primary_structure: str
    allowed_structures: list[str] = Field(default_factory=list)
    templates_require_legal_review: bool = True
    # Pilot: skip human queue for internal deal memos (contract_send still requires approval).
    auto_approve_deal_memo_publish: bool = False
    operations: DealOperationsConfig = Field(default_factory=DealOperationsConfig)


class ComplianceConfig(BaseModel):
    allowed_outreach_channels: list[str] = Field(default_factory=list)
    require_human_approval_for: list[str] = Field(default_factory=list)
    tcpa_can_spam_review_required: bool = True


class ScoringWeights(BaseModel):
    zoning_permitted_surface_parking: int = 40
    zoning_conditional_surface_parking: int = 0
    lot_size: int = 20
    corner_lot: int = 10
    near_demand_generator_m: int = 30
    near_paid_parking_comps: int = 0


class ParkingRateCompObservation(BaseModel):
    """Benchmark paid-parking rate near a parcel (pilot YAML and/or Postgres ``parking_rate_comps``)."""

    name: str
    lat: float
    lon: float
    hourly_mid_usd: float
    source_note: str | None = None
    origin: str = "pilot"
    distance_m: float | None = None


class ParkingRateFallbackEntry(BaseModel):
    """Indicative hourly rate when no paid parking comps exist nearby."""

    hourly_mid_usd: float
    source_note: str | None = None


class ParkingRateFallbackConfig(BaseModel):
    """County / default surface-lot rate benchmarks — see docs/TOP-PARCEL-DEAL-CONTEXT.md."""

    default_hourly_mid_usd: float = 8.0
    default_source_note: str | None = None
    counties: dict[str, ParkingRateFallbackEntry] = Field(default_factory=dict)
    # Confidence multiplier when revenue uses fallback only (no local comps).
    confidence_factor: float = 0.55


class PoiDemandConfig(BaseModel):
    """OSM commercial POI density for revenue occupancy — see docs/TOP-PARCEL-DEAL-CONTEXT.md."""

    radius_m: int = 400
    saturation_count: float = 12.0
    min_occupancy_factor: float = 0.40
    max_occupancy_factor: float = 1.05


class ScoringConfig(BaseModel):
    min_lot_sqft: int = 5000
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    demand_generator_buffer_m: int = 400
    # Optional YAML file(s) merged into demand_generators at load (relative to pilot config dir).
    demand_generators_path: str | None = None
    demand_generators_paths: list[str] = Field(default_factory=list)
    demand_generators: list[dict[str, Any]] = Field(default_factory=list)
    # Latest score at or above this value is treated as a "qualified" lot for listing filters.
    qualified_min_score: float = 55.0
    # Optional static comps in YAML; merged with DB comps at score time when wired.
    parking_rate_comps: list[ParkingRateCompObservation] = Field(default_factory=list)
    parking_rate_comp_radius_m: float = 2500.0
    # Second-pass search when primary radius returns too few comps (revenue + scoring).
    parking_rate_comp_expanded_radius_m: float = 7500.0
    parking_rate_comp_min_for_full_credit: int = 2
    parking_rate_comp_max_used: int = 8
    parking_rate_fallbacks: ParkingRateFallbackConfig | None = None
    poi_demand: PoiDemandConfig | None = None


class DataSourcesConfig(BaseModel):
    parcel_vendor: str = "TBD"
    zoning_vendor: str = "TBD"
    poi_source: str = "TBD"


class PilotConfig(BaseModel):
    crs: str = "EPSG:4326"
    region: RegionConfig
    deal: DealConfig
    compliance: ComplianceConfig
    scoring: ScoringConfig
    data_sources: DataSourcesConfig = Field(default_factory=DataSourcesConfig)


def _load_demand_generator_file(extra_path: Path) -> list[dict[str, Any]]:
    if not extra_path.is_file():
        msg = f"demand generators file not found: {extra_path}"
        raise FileNotFoundError(msg)
    extra_raw = yaml.safe_load(extra_path.read_text())
    if isinstance(extra_raw, list):
        return [g for g in extra_raw if isinstance(g, dict)]
    if isinstance(extra_raw, dict):
        gens = extra_raw.get("demand_generators") or extra_raw.get("generators") or []
        return [g for g in gens if isinstance(g, dict)]
    return []


def _merge_demand_generators_from_paths(raw: dict[str, Any], pilot_path: Path) -> None:
    scoring = raw.get("scoring")
    if not isinstance(scoring, dict):
        return
    rel_paths: list[str] = []
    single = scoring.get("demand_generators_path")
    if isinstance(single, str) and single.strip():
        rel_paths.append(single.strip())
    for rel in scoring.get("demand_generators_paths") or []:
        if isinstance(rel, str) and rel.strip():
            rel_paths.append(rel.strip())
    if not rel_paths:
        return

    inline = list(scoring.get("demand_generators") or [])
    seen = {str(g.get("name", "")).strip().lower() for g in inline if isinstance(g, dict)}
    for rel in rel_paths:
        extra_path = Path(rel)
        if not extra_path.is_absolute():
            extra_path = pilot_path.parent / extra_path
        for gen in _load_demand_generator_file(extra_path):
            key = str(gen.get("name", "")).strip().lower()
            if key and key in seen:
                continue
            inline.append(gen)
            if key:
                seen.add(key)
    scoring["demand_generators"] = inline


def load_pilot_config(path: str | Path) -> PilotConfig:
    pilot_path = Path(path)
    raw = yaml.safe_load(pilot_path.read_text())
    if not isinstance(raw, dict):
        msg = f"Invalid pilot config (expected mapping): {pilot_path}"
        raise TypeError(msg)
    _merge_demand_generators_from_paths(raw, pilot_path)
    return PilotConfig.model_validate(raw)
