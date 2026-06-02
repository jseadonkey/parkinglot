from __future__ import annotations

from typing import Any

__all__ = ["iter_parcels_from_geojson_dict"]


def __getattr__(name: str) -> Any:
    if name == "iter_parcels_from_geojson_dict":
        from parking_ingestion.geojson_loader import iter_parcels_from_geojson_dict

        return iter_parcels_from_geojson_dict
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
