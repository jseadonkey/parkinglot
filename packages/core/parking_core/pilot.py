from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class InScopeConfig(BaseModel):
    """Kent city + King unincorporated only — excludes other King County incorporated places."""

    kent_city_boundary_geojson: str = "data/boundaries/wa/kent_city_census_places.geojson"
    excluded_incorporated_places_geojson: str = (
        "data/boundaries/wa/king_county_incorporated_excluding_kent.geojson"
    )


class RegionConfig(BaseModel):
    name: str
    state_fips: str
    county_fips: list[str] = Field(default_factory=list)
    primary_metro_cbsa: str | None = None
    in_scope: InScopeConfig | None = None


class OperationsConfig(BaseModel):
    """What we acquire and operate — guides zoning interpretation, scoring, and outreach."""

    site_use: str = "standalone_unmanned_parking_lot"
    lease_model: str = "master_lease"
    summary: str = (
        "Master-lease land for standalone, unmanned surface parking only "
        "(no attendants, no valet, no garages we staff)."
    )
    partial_lot_note: str = (
        "A site may still qualify if the owner developed part of the lot (e.g. a building on one half) "
        "while a suitable undeveloped portion remains for unmanned parking — subject to zoning and counsel review."
    )
    excluded: list[str] = Field(
        default_factory=lambda: [
            "accessory parking serving another tenant's building as the only use",
            "attended or valet parking operations",
            "structured garages requiring staffing",
            "mixed-use development where parking is not the primary ground lease",
        ]
    )


class DealConfig(BaseModel):
    primary_structure: str
    allowed_structures: list[str] = Field(default_factory=list)
    templates_require_legal_review: bool = True
    operations: OperationsConfig = Field(default_factory=OperationsConfig)


class ComplianceConfig(BaseModel):
    allowed_outreach_channels: list[str] = Field(default_factory=list)
    require_human_approval_for: list[str] = Field(default_factory=list)
    tcpa_can_spam_review_required: bool = True


class ScoringWeights(BaseModel):
    zoning_permitted_surface_parking: int = 40
    lot_size: int = 20
    corner_lot: int = 10
    near_demand_generator_m: int = 30
    near_parking_comp_m: int = 0


class ParkingCompMarketConfig(BaseModel):
    """Curated paid-parking comps — distance + rate for market-demand scoring."""

    enabled: bool = False
    comps_path: str = "data/pilot/kent_king_parking_comps.yaml"
    buffer_m: int = 800
    min_rate_usd_per_day: float = 6.0
    premium_rate_usd_per_day: float = 15.0


class ScoringConfig(BaseModel):
    min_lot_sqft: int = 5000
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    demand_generator_buffer_m: int = 400
    demand_generators: list[dict[str, Any]] = Field(default_factory=list)
    parking_comp_market: ParkingCompMarketConfig = Field(default_factory=ParkingCompMarketConfig)
    qualified_min_score: float = 55.0


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


def load_pilot_config(path: str | Path) -> PilotConfig:
    raw = yaml.safe_load(Path(path).read_text())
    return PilotConfig.model_validate(raw)
