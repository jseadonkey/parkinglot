"""Nearest curated paid-parking comp lookup (distance + rate) for market-demand scoring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from parking_core.pilot import ParkingCompMarketConfig, PilotConfig
from parking_core.pilot_scope import _repo_relative

from parking_ingestion.parcel_metrics import haversine_m

CompKind = Literal["surface", "garage", "hotel", "municipal", "park_ride", "event"]


@dataclass(frozen=True)
class ParkingComp:
    id: str
    name: str
    lat: float
    lon: float
    kind: str
    rate_usd_per_day: float
    rate_usd_per_hour: float | None
    notes: str | None


@dataclass(frozen=True)
class NearestParkingComp:
    comp: ParkingComp
    distance_m: float

    def as_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.comp.id,
            "name": self.comp.name,
            "kind": self.comp.kind,
            "rate_usd_per_day": self.comp.rate_usd_per_day,
            "rate_usd_per_hour": self.comp.rate_usd_per_hour,
            "distance_m": round(self.distance_m, 1),
            "notes": self.comp.notes,
        }


def load_parking_comps(path: str | Path) -> list[ParkingComp]:
    p = Path(path)
    raw = yaml.safe_load(p.read_text())
    if not isinstance(raw, dict):
        return []
    items = raw.get("comps") or []
    out: list[ParkingComp] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not cid or not name:
            continue
        try:
            lat = float(item["lat"])
            lon = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        rate_day = float(item.get("rate_usd_per_day") or 0.0)
        rate_hr_raw = item.get("rate_usd_per_hour")
        rate_hr = float(rate_hr_raw) if rate_hr_raw is not None else None
        out.append(
            ParkingComp(
                id=cid,
                name=name,
                lat=lat,
                lon=lon,
                kind=str(item.get("kind") or "surface"),
                rate_usd_per_day=rate_day,
                rate_usd_per_hour=rate_hr,
                notes=str(item["notes"]).strip() if item.get("notes") else None,
            )
        )
    return out


def effective_daily_rate(comp: ParkingComp) -> float:
    """Best available daily rate; derive from hourly when day rate is zero."""
    if comp.rate_usd_per_day > 0:
        return comp.rate_usd_per_day
    if comp.rate_usd_per_hour and comp.rate_usd_per_hour > 0:
        return comp.rate_usd_per_hour * 10.0
    return 0.0


def find_nearest_parking_comp(
    lat: float,
    lon: float,
    comps: list[ParkingComp],
    *,
    min_rate_usd_per_day: float = 0.0,
    prefer_kinds: tuple[str, ...] = ("surface", "municipal", "event", "hotel", "garage", "park_ride"),
) -> NearestParkingComp | None:
    """Shortest-distance comp meeting ``min_rate_usd_per_day`` (or derived from hourly).

    When multiple comps tie within 25 m, prefer ``prefer_kinds`` order (surface-first default).
    """
    if not comps:
        return None
    ranked: list[NearestParkingComp] = []
    for comp in comps:
        rate = effective_daily_rate(comp)
        if rate < min_rate_usd_per_day:
            continue
        d = haversine_m(lat, lon, comp.lat, comp.lon)
        ranked.append(NearestParkingComp(comp=comp, distance_m=d))
    if not ranked:
        return None
    ranked.sort(key=lambda x: x.distance_m)
    best_d = ranked[0].distance_m
    close = [r for r in ranked if r.distance_m <= best_d + 25.0]
    kind_rank = {k: i for i, k in enumerate(prefer_kinds)}

    def sort_key(r: NearestParkingComp) -> tuple[float, int, float]:
        return (r.distance_m, kind_rank.get(r.comp.kind, 99), -effective_daily_rate(r.comp))

    close.sort(key=sort_key)
    return close[0]


def parking_comp_metrics_for_point(
    lat: float,
    lon: float,
    comp_cfg: ParkingCompMarketConfig,
    *,
    repo_root: Path | None = None,
    pilot_config_path: str | Path | None = None,
) -> tuple[float | None, dict[str, Any] | None]:
    """Return ``(distance_m, snapshot)`` for nearest qualifying comp, or ``(None, None)``."""
    rel = (comp_cfg.comps_path or "").strip()
    if not rel:
        return None, None
    path = _repo_relative(rel, repo_root=repo_root, pilot_config_path=pilot_config_path)
    comps = load_parking_comps(path)
    nearest = find_nearest_parking_comp(
        lat,
        lon,
        comps,
        min_rate_usd_per_day=float(comp_cfg.min_rate_usd_per_day),
    )
    if nearest is None:
        return None, None
    return nearest.distance_m, nearest.as_snapshot()


def parking_comp_metrics_from_pilot(
    lat: float,
    lon: float,
    pilot: PilotConfig,
    *,
    repo_root: Path | None = None,
    pilot_config_path: str | Path | None = None,
) -> tuple[float | None, dict[str, Any] | None]:
    return parking_comp_metrics_for_point(
        lat,
        lon,
        pilot.scoring.parking_comp_market,
        repo_root=repo_root,
        pilot_config_path=pilot_config_path,
    )
