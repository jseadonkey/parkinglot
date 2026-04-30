from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import get_settings
from parking_core.pilot import load_pilot_config


def _template_dir() -> Path:
    local = Path(__file__).resolve().parent / "templates"
    if local.exists():
        return local
    return Path("/app/services/api/app/templates")


def render_ground_lease_draft(*, apn: str, county_fips: str, owner_name: str, lot_sqft: float | None) -> str:
    base = _template_dir()
    env = Environment(
        loader=FileSystemLoader(str(base)),
        autoescape=select_autoescape(enabled_extensions=()),
    )
    pilot = load_pilot_config(get_settings().pilot_config_path)
    tpl = env.get_template("contract_ground_lease.md.j2")
    return tpl.render(
        apn=apn,
        county_fips=county_fips,
        owner_name=owner_name,
        lot_sqft=lot_sqft,
        deal_structure=pilot.deal.primary_structure,
        region_name=pilot.region.name,
        disclaimer="DRAFT — NOT FOR EXECUTION — REQUIRES HUMAN AND COUNSEL APPROVAL.",
    )
