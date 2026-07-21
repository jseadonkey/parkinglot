"""OpenStreetMap Overpass queries for commercial POI density near a parcel."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_USER_AGENT = "parkinglot-pilot/1.0 (commercial POI density; contact: ops@vspecialist.com)"

# Retail, food, healthcare, tourism, office — drivers of paid parking demand.
_OVERPASS_POI_QUERY = """
[out:json][timeout:25];
(
  nwr(around:{radius},{lat},{lon})["amenity"~"restaurant|cafe|fast_food|bar|pub|pharmacy|clinic|doctors|hospital|bank|cinema|theatre|nightclub|food_court|ice_cream|biergarten"];
  nwr(around:{radius},{lat},{lon})["shop"~"supermarket|mall|department_store|convenience|clothing|beauty|hairdresser|bakery|butcher|electronics|furniture|hardware|car"];
  nwr(around:{radius},{lat},{lon})["healthcare"];
  nwr(around:{radius},{lat},{lon})["tourism"~"museum|attraction|hotel|gallery"];
  nwr(around:{radius},{lat},{lon})["leisure"~"fitness_centre|sports_centre|stadium"];
  nwr(around:{radius},{lat},{lon})["office"];
);
out ids;
"""


def build_overpass_poi_query(*, lat: float, lon: float, radius_m: int) -> str:
    r = max(50, min(int(radius_m), 2000))
    return _OVERPASS_POI_QUERY.format(radius=r, lat=f"{lat:.6f}", lon=f"{lon:.6f}")


def count_commercial_pois_osm(
    lat: float,
    lon: float,
    *,
    radius_m: int = 400,
    overpass_url: str = DEFAULT_OVERPASS_URL,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_sec: float = 30.0,
) -> int:
    """Return count of distinct OSM elements matching commercial POI tags within ``radius_m``."""
    query = build_overpass_poi_query(lat=lat, lon=lon, radius_m=radius_m)
    body = query.encode("utf-8")
    req = urllib.request.Request(
        overpass_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": user_agent,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        raise RuntimeError(f"Overpass POI query failed: {exc}") from exc

    elements = payload.get("elements") or []
    return len(elements)


def count_commercial_pois_osm_throttled(
    lat: float,
    lon: float,
    *,
    radius_m: int = 400,
    overpass_url: str = DEFAULT_OVERPASS_URL,
    user_agent: str = DEFAULT_USER_AGENT,
    delay_sec: float = 1.0,
    last_request_at: float | None = None,
) -> tuple[int, float]:
    """Like ``count_commercial_pois_osm`` but sleeps to respect public Overpass rate limits."""
    if last_request_at is not None and delay_sec > 0:
        elapsed = time.monotonic() - last_request_at
        if elapsed < delay_sec:
            time.sleep(delay_sec - elapsed)
    started = time.monotonic()
    count = count_commercial_pois_osm(
        lat,
        lon,
        radius_m=radius_m,
        overpass_url=overpass_url,
        user_agent=user_agent,
    )
    return count, started


# ---------------------------------------------------------------------------
# Weighted demand intensity — magnitude of parking demand, not POI count.
# One hospital or stadium drives more paid-parking demand than several small
# shops, so anchors carry "pull" weights instead of counting 1 each.
# ---------------------------------------------------------------------------

# Heavy anchors pull visitors from farther away than a corner cafe.
HEAVY_ANCHOR_RADIUS_M = 800

# (tag key, regex of values) -> pull weight per matching element.
_HEAVY_ANCHOR_WEIGHTS: list[tuple[str, str, float]] = [
    ("leisure", r"^stadium$", 15.0),
    ("amenity", r"^(hospital|university)$", 12.0),
    ("amenity", r"^(conference_centre|events_venue|exhibition_centre)$", 10.0),
    ("railway", r"^station$", 8.0),
    ("amenity", r"^(ferry_terminal|bus_station|college)$", 8.0),
    ("shop", r"^mall$", 8.0),
    ("amenity", r"^(courthouse|townhall|arts_centre)$", 6.0),
    ("shop", r"^department_store$", 6.0),
    ("amenity", r"^(theatre|cinema|casino)$", 5.0),
    ("tourism", r"^(museum|attraction|theme_park|zoo)$", 5.0),
    ("leisure", r"^(sports_centre|water_park)$", 4.0),
    ("tourism", r"^hotel$", 4.0),
]

_MEDIUM_POI_WEIGHTS: list[tuple[str, str, float]] = [
    ("shop", r"^(supermarket|wholesale)$", 3.0),
    ("amenity", r"^(clinic|nightclub|food_court)$", 3.0),
    ("healthcare", r".", 2.0),
    ("office", r".", 2.0),
    ("amenity", r"^(bank|biergarten)$", 2.0),
    ("leisure", r"^fitness_centre$", 2.0),
]

_HEAVY_ANCHOR_QUERY = """
[out:json][timeout:30];
(
  nwr(around:{heavy_r},{lat},{lon})["amenity"~"hospital|university|college|courthouse|townhall|conference_centre|events_venue|exhibition_centre|arts_centre|theatre|cinema|casino|ferry_terminal|bus_station"];
  nwr(around:{heavy_r},{lat},{lon})["leisure"~"stadium|sports_centre|water_park"];
  nwr(around:{heavy_r},{lat},{lon})["railway"="station"];
  nwr(around:{heavy_r},{lat},{lon})["shop"~"mall|department_store"];
  nwr(around:{heavy_r},{lat},{lon})["tourism"~"museum|attraction|theme_park|zoo|hotel"];
  nwr(around:{light_r},{lat},{lon})["amenity"~"restaurant|cafe|fast_food|bar|pub|pharmacy|clinic|doctors|bank|nightclub|food_court|ice_cream|biergarten"];
  nwr(around:{light_r},{lat},{lon})["shop"~"supermarket|wholesale|convenience|clothing|beauty|hairdresser|bakery|butcher|electronics|furniture|hardware|car"];
  nwr(around:{light_r},{lat},{lon})["healthcare"];
  nwr(around:{light_r},{lat},{lon})["leisure"="fitness_centre"];
  nwr(around:{light_r},{lat},{lon})["office"];
);
out tags;
"""


def _element_pull_weight(tags: dict) -> tuple[float, bool]:
    """Return (pull weight, is_heavy_anchor) for one OSM element's tags."""
    import re as _re

    for key, pattern, weight in _HEAVY_ANCHOR_WEIGHTS:
        val = tags.get(key)
        if isinstance(val, str) and _re.match(pattern, val):
            return weight, True
    for key, pattern, weight in _MEDIUM_POI_WEIGHTS:
        val = tags.get(key)
        if isinstance(val, str) and _re.match(pattern, val):
            return weight, False
    return 1.0, False


def demand_intensity_from_elements(elements: list[dict]) -> tuple[float, int]:
    """Sum weighted parking-demand pull over OSM elements → (intensity, heavy anchor count)."""
    intensity = 0.0
    heavy = 0
    for el in elements:
        tags = el.get("tags")
        if not isinstance(tags, dict):
            continue
        weight, is_heavy = _element_pull_weight(tags)
        intensity += weight
        if is_heavy:
            heavy += 1
    return round(intensity, 1), heavy


def demand_intensity_osm(
    lat: float,
    lon: float,
    *,
    light_radius_m: int = 400,
    heavy_radius_m: int = HEAVY_ANCHOR_RADIUS_M,
    overpass_url: str = DEFAULT_OVERPASS_URL,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_sec: float = 40.0,
) -> tuple[float, int, int]:
    """Weighted parking-demand intensity near a point.

    Returns ``(intensity, heavy_anchor_count, raw_element_count)``. Heavy anchors
    (hospitals, universities, stadiums, transit stations, malls...) are searched
    at ``heavy_radius_m``; everyday commercial POIs at ``light_radius_m``.
    """
    query = _HEAVY_ANCHOR_QUERY.format(
        heavy_r=max(100, min(int(heavy_radius_m), 3000)),
        light_r=max(50, min(int(light_radius_m), 2000)),
        lat=f"{lat:.6f}",
        lon=f"{lon:.6f}",
    )
    req = urllib.request.Request(
        overpass_url,
        data=query.encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": user_agent,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        raise RuntimeError(f"Overpass demand-intensity query failed: {exc}") from exc

    elements = payload.get("elements") or []
    intensity, heavy = demand_intensity_from_elements(elements)
    return intensity, heavy, len(elements)


def demand_intensity_osm_throttled(
    lat: float,
    lon: float,
    *,
    light_radius_m: int = 400,
    heavy_radius_m: int = HEAVY_ANCHOR_RADIUS_M,
    overpass_url: str = DEFAULT_OVERPASS_URL,
    user_agent: str = DEFAULT_USER_AGENT,
    delay_sec: float = 1.0,
    last_request_at: float | None = None,
) -> tuple[float, int, int, float]:
    """Throttled ``demand_intensity_osm`` → (intensity, heavy_count, element_count, started_at)."""
    if last_request_at is not None and delay_sec > 0:
        elapsed = time.monotonic() - last_request_at
        if elapsed < delay_sec:
            time.sleep(delay_sec - elapsed)
    started = time.monotonic()
    intensity, heavy, n = demand_intensity_osm(
        lat,
        lon,
        light_radius_m=light_radius_m,
        heavy_radius_m=heavy_radius_m,
        overpass_url=overpass_url,
        user_agent=user_agent,
    )
    return intensity, heavy, n, started
