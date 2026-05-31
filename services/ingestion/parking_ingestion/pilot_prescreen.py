"""Pre-ingest parcel funnel — geography, land use, lot size, optional zoning."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from parking_core.pilot import load_pilot_config
from parking_core.pilot_scope import classify_from_in_scope_config, discover_repo_root
from shapely.geometry import Point, shape

from parking_ingestion.building_prescreen import building_value_prescreen_pass
from parking_ingestion.zoning_rules import (
    effective_zoning_rules_path,
    load_zoning_rules,
    lookup_zone_entry,
)


@dataclass
class PrescreenStats:
    scanned: int = 0
    kept: int = 0
    rejected_geography: int = 0
    rejected_land_use: int = 0
    rejected_lot_size: int = 0
    rejected_zoning: int = 0
    rejected_building_value: int = 0
    rejected_no_geometry: int = 0
    kent_city: int = 0
    king_unincorporated: int = 0


@dataclass
class PrescreenConfig:
    geography_enabled: bool = True
    land_use_enabled: bool = True
    exclude_landuse_codes: set[int] = field(default_factory=set)
    lot_size_enabled: bool = True
    min_sqft: float = 5000.0
    area_field: str = "Shape__Area"
    zoning_enabled: bool = True
    zoning_mode: str = "drop_explicit_false"
    kent_zone_field: str = "Short_Name"
    king_zone_field: str = "CURRZONE"
    building_value_enabled: bool = True
    max_building_share: float = 0.70


def load_prescreen_config(path: str | Path) -> PrescreenConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    lu = raw.get("land_use") or {}
    ls = raw.get("lot_size") or {}
    zn = raw.get("zoning") or {}
    geo = raw.get("geography") or {}
    bv = raw.get("building_value") or {}
    exclude = {int(c) for c in (lu.get("exclude_codes") or [])}
    return PrescreenConfig(
        geography_enabled=bool(geo.get("enabled", True)),
        land_use_enabled=bool(lu.get("enabled", True)),
        exclude_landuse_codes=exclude,
        lot_size_enabled=bool(ls.get("enabled", True)),
        min_sqft=float(ls.get("min_sqft") or 5000),
        area_field=str(ls.get("area_field") or "Shape__Area"),
        zoning_enabled=bool(zn.get("enabled", True)),
        zoning_mode=str(zn.get("mode") or "drop_explicit_false").strip().lower(),
        kent_zone_field=str(zn.get("kent_zone_field") or "Short_Name"),
        king_zone_field=str(zn.get("king_zone_field") or "CURRZONE"),
        building_value_enabled=bool(bv.get("enabled", True)),
        max_building_share=float(bv.get("max_building_share") or 0.70),
    )


def _lot_sqft_from_feature(props: dict[str, Any], area_field: str) -> float | None:
    raw = props.get(area_field)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _landuse_code(props: dict[str, Any]) -> int | None:
    raw = props.get("LANDUSE_CD")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def zone_explicitly_forbidden(
    zoning_code: str | None,
    jurisdiction_key: str | None,
    rules: dict[str, Any],
) -> bool:
    """True only when rules YAML explicitly marks the zone as not allowing surface parking."""
    jk = (jurisdiction_key or "").strip().lower()
    if not jk or zoning_code is None or not str(zoning_code).strip():
        return False
    jurisdictions = rules.get("jurisdictions") or {}
    block = jurisdictions.get(jk)
    if not isinstance(block, dict):
        return False
    zones = block.get("zones") or {}
    if not isinstance(zones, dict):
        return False
    zones = block.get("zones") or {}
    entry = lookup_zone_entry(zones if isinstance(zones, dict) else {}, str(zoning_code))
    if entry is None:
        return False
    if isinstance(entry, bool):
        return not entry
    if isinstance(entry, dict) and "allows_surface_parking" in entry:
        return not bool(entry["allows_surface_parking"])
    return False


def zoning_prescreen_pass(
    zoning_code: str | None,
    jurisdiction_key: str | None,
    rules: dict[str, Any],
    *,
    mode: str,
) -> bool:
    if mode == "off":
        return True
    if mode == "strict":
        from parking_ingestion.zoning_rules import resolve_surface_parking

        return resolve_surface_parking(zoning_code, jurisdiction_key, None, rules)
    # drop_explicit_false (default)
    return not zone_explicitly_forbidden(zoning_code, jurisdiction_key, rules)


class PilotParcelPrescreener:
    """Stream filter for WaTech (or any) GeoJSON parcel features."""

    def __init__(
        self,
        *,
        pilot_config_path: str | Path,
        prescreen: PrescreenConfig,
        zoning_lookup: Any | None = None,
        rules_path: Path | None = None,
    ) -> None:
        self.pilot = load_pilot_config(pilot_config_path)
        self.prescreen = prescreen
        self.repo_root = discover_repo_root(pilot_config_path=pilot_config_path)
        self.pilot_config_path = pilot_config_path
        self.zoning_lookup = zoning_lookup
        eff = effective_zoning_rules_path(rules_path)
        self.rules = load_zoning_rules(eff)

    def _in_geography(self, lon: float, lat: float) -> bool:
        if not self.prescreen.geography_enabled:
            return True
        if self.pilot.region.in_scope is None:
            return True
        return classify_from_in_scope_config(
            lon,
            lat,
            self.pilot.region.in_scope,
            repo_root=self.repo_root,
            pilot_config_path=self.pilot_config_path,
        )

    def _jurisdiction_for_point(self, lon: float, lat: float) -> tuple[str, str | None]:
        from parking_core.pilot_scope import _repo_relative, _prepared_union, parcel_centroid_in_prepared

        in_scope = self.pilot.region.in_scope
        if in_scope is None:
            return "king_unincorporated", None
        kent_path = _repo_relative(
            in_scope.kent_city_boundary_geojson,
            repo_root=self.repo_root,
            pilot_config_path=self.pilot_config_path,
        )
        kent_prep = _prepared_union(str(kent_path.resolve()), "kent")
        pt = Point(lon, lat)
        if parcel_centroid_in_prepared(pt, kent_prep):
            return "kent_city", None
        return "king_unincorporated", None

    def evaluate_feature(self, feat: dict[str, Any]) -> tuple[bool, dict[str, Any] | None, str | None]:
        """Return (keep, enriched_properties_or_none, reject_reason)."""
        geom = feat.get("geometry")
        if not geom:
            return False, None, "no_geometry"
        try:
            shp = shape(geom)
        except Exception:
            return False, None, "bad_geometry"
        if shp.is_empty:
            return False, None, "empty_geometry"
        c = shp.centroid
        lon, lat = float(c.x), float(c.y)

        if not self._in_geography(lon, lat):
            return False, None, "geography"

        props = dict(feat.get("properties") or {})
        if self.prescreen.land_use_enabled:
            code = _landuse_code(props)
            if code is not None and code in self.prescreen.exclude_landuse_codes:
                return False, None, "land_use"

        lot_sqft = _lot_sqft_from_feature(props, self.prescreen.area_field)
        if self.prescreen.lot_size_enabled:
            if lot_sqft is None or lot_sqft < self.prescreen.min_sqft:
                return False, None, "lot_size"

        juris = "king_unincorporated"
        zone: str | None = None
        if self.zoning_lookup is not None:
            juris_key, inside_kent = self._jurisdiction_for_point(lon, lat)
            juris = juris_key
            zone = self.zoning_lookup.zone_at(lon, lat, juris_key)
        elif self.prescreen.zoning_enabled:
            juris, _ = self._jurisdiction_for_point(lon, lat)

        if self.prescreen.zoning_enabled and self.prescreen.zoning_mode != "off":
            if not zoning_prescreen_pass(zone, juris, self.rules, mode=self.prescreen.zoning_mode):
                return False, None, "zoning"

        if self.prescreen.building_value_enabled:
            if not building_value_prescreen_pass(
                props,
                max_building_share=self.prescreen.max_building_share,
            ):
                return False, None, "building_value"

        apn = str(
            props.get("PARCEL_ID_NR")
            or props.get("ORIG_PARCEL_ID")
            or props.get("APN")
            or props.get("apn")
            or ""
        ).strip()
        county = str(props.get("COUNTY_FIPS") or "53033").strip()

        enriched = dict(props)
        enriched["APN"] = apn
        enriched["COUNTY_FIPS"] = county
        if lot_sqft is not None:
            enriched["LOT_SQFT"] = lot_sqft
        if zone:
            enriched["ZONING"] = zone
        enriched["ZONING_JURISDICTION"] = juris
        enriched["PILOT_PRESCREEN"] = True

        return True, enriched, None

    def filter_feature_collection(
        self,
        features: list[dict[str, Any]],
        stats: PrescreenStats | None = None,
    ) -> list[dict[str, Any]]:
        st = stats or PrescreenStats()
        out: list[dict[str, Any]] = []
        for feat in features:
            st.scanned += 1
            keep, props, reason = self.evaluate_feature(feat)
            if not keep:
                if reason == "no_geometry" or reason == "bad_geometry" or reason == "empty_geometry":
                    st.rejected_no_geometry += 1
                elif reason == "geography":
                    st.rejected_geography += 1
                elif reason == "land_use":
                    st.rejected_land_use += 1
                elif reason == "lot_size":
                    st.rejected_lot_size += 1
                elif reason == "zoning":
                    st.rejected_zoning += 1
                elif reason == "building_value":
                    st.rejected_building_value += 1
                continue
            st.kept += 1
            juris = (props or {}).get("ZONING_JURISDICTION")
            if juris == "kent_city":
                st.kent_city += 1
            elif juris == "king_unincorporated":
                st.king_unincorporated += 1
            out.append(
                {
                    "type": "Feature",
                    "geometry": feat["geometry"],
                    "properties": props,
                }
            )
        return out
