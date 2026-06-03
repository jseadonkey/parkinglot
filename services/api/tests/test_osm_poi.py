from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from parking_ingestion.osm_poi import build_overpass_poi_query, count_commercial_pois_osm


def test_build_overpass_poi_query_includes_coords() -> None:
    q = build_overpass_poi_query(lat=39.29, lon=-76.61, radius_m=400)
    assert "39.290000" in q
    assert "-76.610000" in q
    assert "around:400" in q


def test_count_commercial_pois_osm_parses_response() -> None:
    payload = json.dumps({"elements": [{"type": "node", "id": 1}, {"type": "node", "id": 2}]}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert count_commercial_pois_osm(39.29, -76.61, radius_m=400) == 2
