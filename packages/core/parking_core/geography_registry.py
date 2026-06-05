from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

GeographyType = Literal[
    "state",
    "county",
    "county_unincorporated",
    "city",
    "consolidated_city_county",
]

SourceType = Literal[
    "parcel",
    "assessor",
    "boundary",
    "zoning",
    "zoning_rules",
    "poi",
    "registry",
    "recorder",
    "data_quality",
]

CoverageSeverity = Literal["error", "warning", "info"]


class SourceRef(BaseModel):
    """Structured source-of-truth inventory entry."""

    key: str
    name: str
    type: SourceType
    url: str | None = None
    path: str | None = None
    terms_url: str | None = None
    cadence: str | None = None
    coverage: str | None = None
    notes: str | None = None

    @field_validator("key")
    @classmethod
    def _normalize_key(cls, value: str) -> str:
        return value.strip().lower()


class CityInventorySource(BaseModel):
    """Authoritative source used to discover incorporated-city agents."""

    state_fips: str
    state: str
    source_ref: str
    coverage: str = "all_incorporated_places"
    agent_key_template: str = "{state_fips}_{place_geoid}_{slug}"
    jurisdiction_key_template: str = "{slug}_city"
    manifest_path: str | None = None

    @field_validator("state_fips", "source_ref")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class GeographyAgent(BaseModel):
    """A deterministic geography-specific agent binding.

    The "agent" is a config record: it tells the platform which sources,
    zoning jurisdiction key, boundaries, and validation checks apply to a
    city, county, or county-unincorporated area.
    """

    key: str
    name: str
    type: GeographyType
    state_fips: str
    county_fips: str | None = None
    jurisdiction_key: str | None = None
    default_for_county: bool = False
    boundary_path: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    zoning_rules_paths: list[str] = Field(default_factory=list)
    agent_profiles: list[str] = Field(default_factory=lambda: ["identification", "entitlement", "strategic"])
    validation_checks: list[str] = Field(
        default_factory=lambda: [
            "source_refs_present",
            "zoning_jurisdiction_present",
            "zoning_rules_coverage",
        ]
    )
    notes: str | None = None

    @field_validator("key")
    @classmethod
    def _normalize_key(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("source_refs", "zoning_rules_paths", "agent_profiles", "validation_checks")
    @classmethod
    def _strip_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]

    @field_validator("jurisdiction_key")
    @classmethod
    def _normalize_optional_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().lower()
        return stripped or None


class CoverageIssue(BaseModel):
    severity: CoverageSeverity
    code: str
    message: str
    geography_key: str | None = None
    county_fips: str | None = None
    jurisdiction_key: str | None = None


class GeographyRegistry(BaseModel):
    version: int = 1
    description: str | None = None
    generated_geography_paths: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    city_inventory_sources: list[CityInventorySource] = Field(default_factory=list)
    geographies: list[GeographyAgent] = Field(default_factory=list)

    def source_map(self) -> dict[str, SourceRef]:
        return {source.key: source for source in self.sources}

    def geography_map(self) -> dict[str, GeographyAgent]:
        return {geo.key: geo for geo in self.geographies}

    def geographies_for_county(self, county_fips: str) -> list[GeographyAgent]:
        cf = county_fips.strip()
        return [geo for geo in self.geographies if (geo.county_fips or "").strip() == cf]

    def default_jurisdiction_for_county(self, county_fips: str) -> str | None:
        geos = self.geographies_for_county(county_fips)
        for geo in geos:
            if geo.default_for_county and geo.jurisdiction_key:
                return geo.jurisdiction_key
        for geo in geos:
            if geo.type in ("county_unincorporated", "consolidated_city_county") and geo.jurisdiction_key:
                return geo.jurisdiction_key
        return None

    def boundary_geographies_for_county(self, county_fips: str) -> list[GeographyAgent]:
        return [
            geo
            for geo in self.geographies_for_county(county_fips)
            if geo.boundary_path and geo.jurisdiction_key
        ]

    def geography_for_jurisdiction(self, jurisdiction_key: str) -> GeographyAgent | None:
        jk = jurisdiction_key.strip().lower()
        for geo in self.geographies:
            if geo.jurisdiction_key == jk:
                return geo
        return None

    def zoning_rules_paths(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for geo in self.geographies:
            for path in geo.zoning_rules_paths:
                if path not in seen:
                    seen.add(path)
                    out.append(path)
        return out


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    marker = Path("config") / "geography_registry.yaml"
    cwd = Path.cwd()
    if (cwd / marker).is_file():
        return cwd
    for parent in (here.parent, *here.parents):
        if (parent / marker).is_file():
            return parent
    for parent in (cwd, *cwd.parents):
        if (parent / marker).is_file():
            return parent
    app_root = Path("/app")
    if (app_root / marker).is_file():
        return app_root
    return here.parents[2]


def default_geography_registry_path() -> Path:
    return _repo_root() / "config" / "geography_registry.yaml"


def _registry_fragment_path(registry_path: Path, fragment: str) -> Path:
    candidate = Path(fragment)
    if candidate.is_absolute():
        return candidate
    registry_root = registry_path.parent.parent
    registry_root_candidate = registry_root / candidate
    if registry_root_candidate.is_file():
        return registry_root_candidate
    root_candidate = _repo_root() / candidate
    if root_candidate.is_file():
        return root_candidate
    return registry_path.parent / candidate


def _merge_generated_fragments(raw: dict[str, Any], registry_path: Path) -> None:
    for fragment in raw.get("generated_geography_paths") or []:
        if not isinstance(fragment, str) or not fragment.strip():
            continue
        fragment_path = _registry_fragment_path(registry_path, fragment.strip())
        if not fragment_path.is_file():
            continue
        fragment_raw = yaml.safe_load(fragment_path.read_text(encoding="utf-8"))
        if not isinstance(fragment_raw, dict):
            continue
        for key in ("sources", "city_inventory_sources", "geographies"):
            values = fragment_raw.get(key)
            if isinstance(values, list):
                raw.setdefault(key, [])
                raw[key].extend(values)


def _load_registry_uncached(path: str) -> GeographyRegistry:
    registry_path = Path(path)
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"Invalid geography registry (expected mapping): {registry_path}"
        raise TypeError(msg)
    _merge_generated_fragments(raw, registry_path)
    return GeographyRegistry.model_validate(raw)


@lru_cache(maxsize=8)
def _load_registry_cached(path: str) -> GeographyRegistry:
    return _load_registry_uncached(path)


def load_geography_registry(path: str | Path | None = None) -> GeographyRegistry:
    env_path = os.environ.get("GEOGRAPHY_REGISTRY_PATH", "").strip()
    if path is not None:
        registry_path = Path(path)
    elif env_path:
        registry_path = Path(env_path)
    else:
        registry_path = default_geography_registry_path()
    return _load_registry_cached(str(registry_path.resolve()))


def _rules_jurisdictions(zoning_rules: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(zoning_rules, dict):
        return {}
    jurisdictions = zoning_rules.get("jurisdictions")
    return jurisdictions if isinstance(jurisdictions, dict) else {}


def validate_geography_registry(
    registry: GeographyRegistry,
    *,
    pilot_county_fips: list[str] | None = None,
    zoning_rules: dict[str, Any] | None = None,
) -> list[CoverageIssue]:
    """Validate registry coverage without requiring database access."""

    issues: list[CoverageIssue] = []
    source_keys = set(registry.source_map())
    rules_jurisdictions = _rules_jurisdictions(zoning_rules)

    states_with_city_inventory = {src.state_fips for src in registry.city_inventory_sources}
    states_seen = {geo.state_fips for geo in registry.geographies}
    for state_fips in sorted(states_seen):
        if state_fips not in states_with_city_inventory:
            issues.append(
                CoverageIssue(
                    severity="warning",
                    code="missing_city_inventory_source",
                    message=f"State {state_fips} has no incorporated-city inventory source.",
                )
            )

    for geo in registry.geographies:
        for source_ref in geo.source_refs:
            if source_ref not in source_keys:
                issues.append(
                    CoverageIssue(
                        severity="error",
                        code="missing_source_ref",
                        message=f"{geo.key} references unknown source {source_ref}.",
                        geography_key=geo.key,
                        county_fips=geo.county_fips,
                        jurisdiction_key=geo.jurisdiction_key,
                    )
                )
        if not geo.jurisdiction_key and geo.type != "state":
            issues.append(
                CoverageIssue(
                    severity="warning",
                    code="missing_jurisdiction_key",
                    message=f"{geo.key} has no zoning jurisdiction key.",
                    geography_key=geo.key,
                    county_fips=geo.county_fips,
                )
            )
        if geo.jurisdiction_key and rules_jurisdictions:
            block = rules_jurisdictions.get(geo.jurisdiction_key)
            if block is None:
                issues.append(
                    CoverageIssue(
                        severity="warning",
                        code="missing_zoning_rules_block",
                        message=f"{geo.key} has no zoning rules block for {geo.jurisdiction_key}.",
                        geography_key=geo.key,
                        county_fips=geo.county_fips,
                        jurisdiction_key=geo.jurisdiction_key,
                    )
                )
            elif isinstance(block, dict) and not (block.get("zones") or {}):
                issues.append(
                    CoverageIssue(
                        severity="info",
                        code="empty_zoning_rules_block",
                        message=f"{geo.key} has a rules block but no curated zone entries yet.",
                        geography_key=geo.key,
                        county_fips=geo.county_fips,
                        jurisdiction_key=geo.jurisdiction_key,
                    )
                )

    for county_fips in pilot_county_fips or []:
        geos = registry.geographies_for_county(county_fips)
        if not geos:
            issues.append(
                CoverageIssue(
                    severity="error",
                    code="missing_county_agent",
                    message=f"Pilot county {county_fips} has no geography agent.",
                    county_fips=county_fips,
                )
            )
            continue
        if registry.default_jurisdiction_for_county(county_fips) is None:
            issues.append(
                CoverageIssue(
                    severity="error",
                    code="missing_default_jurisdiction",
                    message=f"Pilot county {county_fips} has no default county/unincorporated jurisdiction.",
                    county_fips=county_fips,
                )
            )

    return issues
