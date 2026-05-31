"""SQL helpers for King/Kent pilot geographic scope."""

from __future__ import annotations

from pathlib import Path

from geoalchemy2.shape import to_shape
from parking_core.pilot import PilotConfig, load_pilot_config
from parking_core.pilot_scope import classify_from_in_scope_config, discover_repo_root
from sqlalchemy import true
from sqlalchemy.sql import ColumnElement

from app.config import Settings, get_settings
from app.db.models import Parcel


def load_primary_pilot(settings: Settings | None = None) -> PilotConfig:
    s = settings or get_settings()
    return load_pilot_config(s.pilot_config_path)


def pilot_repo_root(settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    return discover_repo_root(pilot_config_path=s.pilot_config_path)


def parcel_in_scope_clause(*, include_out_of_scope: bool = False) -> ColumnElement[bool]:
    if include_out_of_scope:
        return true()
    return Parcel.pilot_in_scope.is_(True)


def classify_parcel_scope(parcel: Parcel, pilot: PilotConfig | None = None) -> bool:
    """Return whether parcel centroid lies in Kent city or King unincorporated pilot area."""
    settings = get_settings()
    cfg_pilot = pilot or load_primary_pilot(settings)
    in_scope_cfg = cfg_pilot.region.in_scope
    if in_scope_cfg is None or parcel.footprint is None:
        return True
    if cfg_pilot.region.county_fips and parcel.county_fips not in cfg_pilot.region.county_fips:
        return False
    c = to_shape(parcel.footprint).centroid
    return classify_from_in_scope_config(
        float(c.x),
        float(c.y),
        in_scope_cfg,
        repo_root=pilot_repo_root(settings),
        pilot_config_path=settings.pilot_config_path,
    )
