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
