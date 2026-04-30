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


class DealConfig(BaseModel):
    primary_structure: str
    allowed_structures: list[str] = Field(default_factory=list)
    templates_require_legal_review: bool = True


class ComplianceConfig(BaseModel):
    allowed_outreach_channels: list[str] = Field(default_factory=list)
    require_human_approval_for: list[str] = Field(default_factory=list)
    tcpa_can_spam_review_required: bool = True


class ScoringWeights(BaseModel):
    zoning_permitted_surface_parking: int = 40
    lot_size: int = 20
    corner_lot: int = 10
    near_demand_generator_m: int = 30


class ScoringConfig(BaseModel):
    min_lot_sqft: int = 5000
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    demand_generator_buffer_m: int = 400
    demand_generators: list[dict[str, Any]] = Field(default_factory=list)


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
