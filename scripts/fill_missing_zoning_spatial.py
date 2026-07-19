#!/usr/bin/env python3
"""Fill missing WA parcel zoning directly from WAZA polygons in PostGIS.

The normal Phase B overlay joins WAZA to a freshly downloaded WaTech parcel
snapshot and then updates Postgres by APN.  That leaves gaps when APNs drift
between snapshots.  This recovery path spatially joins WAZA polygons directly
to the parcel geometries already in Postgres, so it does not depend on APN.

Ferry County (53019) is deliberately excluded because it has no traditional
zoning districts and is absent from WAZA.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from shapely.geometry import shape
from sqlalchemy import text

from app.db.session import SessionLocal
from parking_ingestion.benton_zoning import fetch_zoning_geojson
from parking_ingestion.wa_county_zoning_build import (
    WAZA_ZONES_LAYER_URL,
    normalize_waza_jurisdiction,
)

FERRY_COUNTY_FIPS = "53019"
WAZA_FIELDS = (
    "ZoneID,ZoneName,Jurisdiction,WAZAZoneGeneral,WAZAZoneSpecific,"
    "UseRetail,UseOffice,UseManufacturing,UseHeavyIndustrial,UseWarehouse"
)
EXTRA_FIELDS = (
    "ZoneName",
    "WAZAZoneGeneral",
    "WAZAZoneSpecific",
    "UseRetail",
    "UseOffice",
    "UseManufacturing",
    "UseHeavyIndustrial",
    "UseWarehouse",
)

COUNT_MISSING = text(
    """
    SELECT count(*)
    FROM parcels
    WHERE county_fips = :cf
      AND (zoning_code IS NULL OR btrim(zoning_code) = '')
    """
)

CREATE_TEMP = text(
    """
    CREATE TEMP TABLE tmp_waza_zones (
        zone_code text NOT NULL,
        zoning_jurisdiction text NOT NULL,
        extra jsonb NOT NULL,
        geom geometry(Geometry, 4326) NOT NULL
    ) ON COMMIT DROP
    """
)

INSERT_ZONE = text(
    """
    INSERT INTO tmp_waza_zones (zone_code, zoning_jurisdiction, extra, geom)
    VALUES (
        :zone_code,
        :zoning_jurisdiction,
        CAST(:extra AS jsonb),
        ST_SetSRID(ST_GeomFromText(:wkt), 4326)
    )
    """
)

UPDATE_MISSING = text(
    """
    WITH matches AS (
        SELECT DISTINCT ON (p.id)
            p.id,
            z.zone_code,
            z.zoning_jurisdiction,
            z.extra
        FROM parcels p
        JOIN tmp_waza_zones z
          ON z.geom && p.footprint
         AND (
              ST_Intersects(z.geom, ST_PointOnSurface(p.footprint))
              OR ST_Intersects(z.geom, p.footprint)
         )
        WHERE p.county_fips = :cf
          AND (p.zoning_code IS NULL OR btrim(p.zoning_code) = '')
        ORDER BY
            p.id,
            CASE
              WHEN ST_Intersects(z.geom, ST_PointOnSurface(p.footprint)) THEN 0
              ELSE 1
            END,
            ST_Area(ST_Intersection(z.geom, p.footprint)) DESC
    )
    UPDATE parcels p
    SET
        zoning_code = m.zone_code,
        raw_properties = coalesce(p.raw_properties, '{}'::jsonb)
          || m.extra
          || jsonb_build_object(
              'ZONING_JURISDICTION', m.zoning_jurisdiction,
              'ZONING_MATCH_METHOD', CAST(:match_method AS text)
          )
    FROM matches m
    WHERE p.id = m.id
    """
)


def _counties_with_missing() -> list[str]:
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT county_fips
                FROM parcels
                WHERE county_fips LIKE '53%'
                  AND county_fips <> :ferry
                  AND (zoning_code IS NULL OR btrim(zoning_code) = '')
                GROUP BY county_fips
                ORDER BY count(*) DESC
                """
            ),
            {"ferry": FERRY_COUNTY_FIPS},
        ).scalars()
        return [str(cf) for cf in rows]
    finally:
        db.close()


def _zone_rows(
    feature_collection: dict[str, Any],
    *,
    zoning_field: str,
    jurisdiction_field: str | None = None,
    fixed_jurisdiction: str = "wa_waza",
    extra_fields: tuple[str, ...] = EXTRA_FIELDS,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for feature in feature_collection.get("features") or []:
        props = feature.get("properties") or {}
        zone_code = str(props.get(zoning_field) or "").strip()
        raw_geom = feature.get("geometry")
        if not zone_code or not isinstance(raw_geom, dict):
            continue
        try:
            geom = shape(raw_geom)
        except Exception:
            continue
        if geom.is_empty:
            continue
        raw_jurisdiction = str(props.get(jurisdiction_field) or "").strip() if jurisdiction_field else ""
        jurisdiction = (
            normalize_waza_jurisdiction(raw_jurisdiction)
            if raw_jurisdiction
            else fixed_jurisdiction
        )
        jurisdiction = jurisdiction or fixed_jurisdiction
        extra = {field: props[field] for field in extra_fields if props.get(field) is not None}
        rows.append(
            {
                "zone_code": zone_code,
                "zoning_jurisdiction": jurisdiction,
                "extra": json.dumps(extra),
                "wkt": geom.wkt,
            }
        )
    return rows


def fill_county(
    county_fips: str,
    *,
    source_url: str = WAZA_ZONES_LAYER_URL,
    zoning_field: str = "ZoneID",
    where: str | None = None,
    out_fields: str = WAZA_FIELDS,
    jurisdiction_field: str | None = "Jurisdiction",
    fixed_jurisdiction: str = "wa_waza",
) -> dict[str, Any]:
    cf = str(county_fips).strip()
    if cf == FERRY_COUNTY_FIPS:
        return {"county_fips": cf, "skipped": True, "reason": "no_traditional_zoning"}

    before_db = SessionLocal()
    try:
        before = int(before_db.scalar(COUNT_MISSING, {"cf": cf}) or 0)
    finally:
        before_db.close()
    if before == 0:
        return {"county_fips": cf, "before_missing": 0, "updated": 0, "after_missing": 0}

    countyfp = cf[-3:]
    collection = fetch_zoning_geojson(
        layer_url=source_url,
        label=f"WAZA direct recovery {cf}",
        where=where or f"COUNTYFP='{countyfp}'",
        out_fields=out_fields,
    )
    extra_fields = tuple(
        field.strip()
        for field in out_fields.split(",")
        if field.strip() and field.strip() != zoning_field
    )
    rows = _zone_rows(
        collection,
        zoning_field=zoning_field,
        jurisdiction_field=jurisdiction_field,
        fixed_jurisdiction=fixed_jurisdiction,
        extra_fields=extra_fields,
    )
    if not rows:
        return {
            "county_fips": cf,
            "before_missing": before,
            "updated": 0,
            "after_missing": before,
            "reason": "no_source_polygons",
        }

    db = SessionLocal()
    try:
        db.execute(CREATE_TEMP)
        for start in range(0, len(rows), 1000):
            db.execute(INSERT_ZONE, rows[start : start + 1000])
        db.execute(text("CREATE INDEX tmp_waza_zones_geom_gix ON tmp_waza_zones USING gist (geom)"))
        db.execute(text("ANALYZE tmp_waza_zones"))
        match_method = (
            "waza_direct_postgis"
            if source_url == WAZA_ZONES_LAYER_URL
            else "official_gis_direct_postgis"
        )
        result = db.execute(UPDATE_MISSING, {"cf": cf, "match_method": match_method})
        updated = int(result.rowcount or 0)
        after = int(db.scalar(COUNT_MISSING, {"cf": cf}) or 0)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return {
        "county_fips": cf,
        "before_missing": before,
        "waza_polygons": len(rows),
        "updated": updated,
        "after_missing": after,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("county_fips", nargs="*", help="Optional county FIPS list")
    parser.add_argument("--source-url", default=WAZA_ZONES_LAYER_URL)
    parser.add_argument("--zoning-field", default="ZoneID")
    parser.add_argument("--where")
    parser.add_argument("--out-fields", default=WAZA_FIELDS)
    parser.add_argument("--jurisdiction-field", default="Jurisdiction")
    parser.add_argument("--fixed-jurisdiction", default="wa_waza")
    args = parser.parse_args()

    counties = [str(cf).strip() for cf in args.county_fips if str(cf).strip()]
    if not counties:
        counties = _counties_with_missing()

    total_updated = 0
    for county_fips in counties:
        try:
            result = fill_county(
                county_fips,
                source_url=args.source_url,
                zoning_field=args.zoning_field,
                where=args.where,
                out_fields=args.out_fields,
                jurisdiction_field=args.jurisdiction_field or None,
                fixed_jurisdiction=args.fixed_jurisdiction,
            )
            total_updated += int(result.get("updated") or 0)
            print("ZONING_RECOVERY", json.dumps(result, sort_keys=True), flush=True)
        except Exception as exc:
            print(
                "ZONING_RECOVERY_ERROR",
                json.dumps({"county_fips": county_fips, "error": str(exc)}, sort_keys=True),
                flush=True,
            )

    print(
        "ZONING_RECOVERY_DONE",
        json.dumps({"counties": len(counties), "updated": total_updated}, sort_keys=True),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
