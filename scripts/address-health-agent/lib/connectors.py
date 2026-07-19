"""Dispatch address source actions — extend here when adding a new scraper/merge path."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Any

from .paths import REPO_ROOT as ROOT

ARCGIS_ADDRESS_SOURCES: dict[str, dict[str, object]] = {
    "pierce_tax_parcels": {
        "url": "https://services2.arcgis.com/1UvBaQ5y1ubjUPmd/arcgis/rest/services/Tax_Parcels/FeatureServer/0",
        "join_fields": ("TaxParcelNumber",),
        "address_fields": ("Site_Address",),
        "city_fields": ("City_State",),
        "zip_fields": ("Zipcode",),
        "mailing_fields": ("Delivery_Address",),
        "owner_fields": ("Business_Name",),
    },
    "snohomish_current_parcels": {
        "url": "https://services6.arcgis.com/z6WYi9VRHfgwgtyW/arcgis/rest/services/Parcels/FeatureServer/0",
        "join_fields": ("PARCEL_ID", "LRSN"),
        "address_fields": ("SITUSLINE1",),
        "city_fields": ("SITUSCITY",),
        "state_fields": ("SITUSSTATE",),
        "zip_fields": ("SITUSZIP",),
        "mailing_fields": ("TAXPRLINE1", "OWNERLINE1"),
        "owner_fields": ("OWNERNAME", "TAXPRNAME"),
    },
    "kitsap_county_parcels": {
        "url": "https://services3.arcgis.com/0IbpLwS460cn4psv/ArcGIS/rest/services/KitsapCounty_Parcels/FeatureServer/0",
        "join_fields": ("PARCEL_ID_NR", "ORIG_PARCEL_ID"),
        "address_fields": ("SITUS_ADDRESS", "SUB_ADDRESS"),
        "city_fields": ("SITUS_CITY_NM",),
        "zip_fields": ("SITUS_ZIP_NR",),
    },
    "thurston_county_parcels": {
        "url": "https://map.co.thurston.wa.us/arcgis/rest/services/Thurston/Thurston_Parcels/FeatureServer/0",
        "join_fields": ("PARCEL_NO",),
        "address_fields": ("SITUS_STRE",),
        "city_fields": ("SITUS_CITY",),
        "zip_fields": ("SITUS_ZIP",),
        "mailing_fields": ("ADDRESS1", "ADDRESS2"),
        "owner_fields": ("OWNER_NAME",),
    },
}

ARCGIS_ADDRESS_SOURCES["kitsap_county_parcels_retry"] = ARCGIS_ADDRESS_SOURCES["kitsap_county_parcels"]
ARCGIS_ADDRESS_SOURCES["thurston_county_parcels_retry"] = ARCGIS_ADDRESS_SOURCES["thurston_county_parcels"]


def _internal_key() -> str:
    env_path = ROOT / "deploy" / ".env"
    if not env_path.is_file():
        return (os.environ.get("INTERNAL_API_KEY") or "").strip()
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("INTERNAL_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def _api_post(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    key = _internal_key()
    body = json.dumps(payload or {}).encode()
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if key:
        headers["X-Internal-Key"] = key
    req = urllib.request.Request(f"http://127.0.0.1:8000{path}", data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode() if exc.fp else str(exc)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"error": raw}
    except Exception as exc:
        return {"error": str(exc)}


def _compose_exec(python_snippet: str) -> dict[str, Any]:
    rel = os.environ.get("COMPOSE_REL", "deploy/docker-compose.production.yml")
    cmd = [
        "docker",
        "compose",
        "-f",
        rel,
        "--env-file",
        "deploy/.env",
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        python_snippet,
    ]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    out = (proc.stdout or "") + (proc.stderr or "")
    return {"exit_code": proc.returncode, "output": out[:2000]}


def _arcgis_backfill_snippet(source_id: str, county_fips: str, limit: int) -> str:
    config = dict(ARCGIS_ADDRESS_SOURCES[source_id])
    config["source_id"] = source_id
    return f"""
import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from sqlalchemy import select

from app.audit import write_audit
from app.candidate_address import target_address_backfill_filters
from app.db.models import Parcel
from app.db.session import SessionLocal
from parking_ingestion.address_normalize import looks_like_street

CONFIG = json.loads({json.dumps(config)!r})
COUNTY_FIPS = {county_fips!r}
LIMIT = {int(limit)}


def _clean(value):
    text = str(value or "").strip()
    if not text or text.lower() in ("none", "null", "nan"):
        return None
    return text


def _variants(value):
    base = _clean(value)
    if not base:
        return []
    variants = [base]
    compact = re.sub(r"[^0-9A-Za-z]", "", base)
    if compact and compact != base:
        variants.append(compact)
    dashed = base.replace("-", "")
    if dashed and dashed not in variants:
        variants.append(dashed)
    out = []
    for item in variants:
        if item not in out:
            out.append(item)
    return out


def _candidate_join_values(parcel, props):
    values = []
    for key in (
        "PARCEL_ID_NR",
        "ORIG_PARCEL_ID",
        "TaxParcelNumber",
        "PARCEL_ID",
        "LRSN",
        "PARCEL_NO",
        "PIN",
        "APN",
    ):
        values.extend(_variants(props.get(key)))
    values.extend(_variants(parcel.apn))
    out = []
    for value in values:
        if value not in out:
            out.append(value)
    return out[:8]


def _first(attrs, keys):
    for key in keys or ():
        value = _clean(attrs.get(key))
        if value:
            return value
    return None


def _query_arcgis(join_field, value):
    escaped = value.replace("'", "''")
    params = urllib.parse.urlencode(
        {{
            "where": f"{{join_field}}='{{escaped}}'",
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
        }}
    )
    url = str(CONFIG["url"]).rstrip("/") + "/query?" + params
    with urllib.request.urlopen(url, timeout=25) as resp:
        payload = json.loads(resp.read().decode())
    features = payload.get("features") or []
    if not features:
        return None
    attrs = features[0].get("attributes") or {{}}
    return attrs if isinstance(attrs, dict) else None


selected = matched = updated = no_match = errors = 0
sample_ids = []

with SessionLocal() as db:
    rows = list(
        db.scalars(
            select(Parcel)
            .where(*target_address_backfill_filters(county_fips=COUNTY_FIPS))
            .order_by(Parcel.created_at.asc(), Parcel.id.asc())
            .limit(LIMIT)
        )
    )
    selected = len(rows)
    for parcel in rows:
        props = dict(parcel.raw_properties or {{}})
        attrs = None
        for value in _candidate_join_values(parcel, props):
            for field in CONFIG.get("join_fields") or ():
                try:
                    attrs = _query_arcgis(str(field), value)
                except Exception:
                    errors += 1
                    attrs = None
                if attrs:
                    break
            if attrs:
                break

        props["WA_ADDRESS_BACKFILL_ATTEMPTED_AT"] = datetime.now(UTC).isoformat()
        if not attrs:
            props["WA_ADDRESS_BACKFILL_STATUS"] = "arcgis_no_match"
            parcel.raw_properties = props
            no_match += 1
            continue

        matched += 1
        street = _first(attrs, CONFIG.get("address_fields"))
        city = _first(attrs, CONFIG.get("city_fields"))
        state = (_first(attrs, CONFIG.get("state_fields")) or "WA").upper()[:2]
        zip_code = _first(attrs, CONFIG.get("zip_fields"))
        mailing = _first(attrs, CONFIG.get("mailing_fields"))
        owner = _first(attrs, CONFIG.get("owner_fields"))

        wrote_address = False
        if street and looks_like_street(street):
            props.setdefault("PROPERTY_ADDRESS", street)
            props.setdefault("SITUS_ADDRESS", street)
            props.setdefault("ADDR_FULL", street)
            wrote_address = True
        if city:
            props.setdefault("SITUS_CITY", city)
            props.setdefault("SITUS_CITY_NM", city)
        if state:
            props.setdefault("SITUS_STATE", state)
        if zip_code:
            props.setdefault("SITUS_ZIP", zip_code[:5])
            props.setdefault("SITUS_ZIP_NR", zip_code[:5])
        if mailing:
            props.setdefault("MAILING_ADDRESS", mailing)
        if owner:
            props.setdefault("OWNER_NAME", owner)

        props["ADDRESS_BACKFILL_SOURCE"] = CONFIG["source_id"]
        props["ADDRESS_SOURCE"] = CONFIG["source_id"]
        props["WA_ADDRESS_BACKFILL_STATUS"] = "arcgis_address_found" if wrote_address else "arcgis_match_no_situs"
        props.setdefault("WA_ADDRESS_BACKFILL_JOIN_FIELDS", list(CONFIG.get("join_fields") or ()))
        parcel.raw_properties = props
        if wrote_address:
            updated += 1
            if len(sample_ids) < 5:
                sample_ids.append(str(parcel.id))

    db.commit()
    write_audit(
        db,
        action="wa_arcgis_address_backfill",
        entity_type="county",
        entity_id=COUNTY_FIPS,
        detail={{
            "source_id": CONFIG["source_id"],
            "selected": selected,
            "matched": matched,
            "updated": updated,
            "no_match": no_match,
            "errors": errors,
            "sample_parcel_ids": sample_ids,
        }},
    )
    db.commit()

print(json.dumps({{
    "source_id": CONFIG["source_id"],
    "county_fips": COUNTY_FIPS,
    "selected": selected,
    "matched": matched,
    "updated": updated,
    "no_match": no_match,
    "errors": errors,
    "sample_parcel_ids": sample_ids,
}}))
"""


def run_connector(source_id: str, *, county_fips: str, limit: int = 250) -> dict[str, Any]:
    """Run the best available action for a catalog source_id."""
    sid = source_id.strip()

    if sid in ("baltimore_realproperty", "baltimore_address_points"):
        result = _api_post(f"/internal/metrics/backfill-baltimore-addresses?limit={limit}&dry_run=false")
        return {"action": "baltimore_address_backfill", "source_id": sid, "result": result}

    if sid == "watech_statewide_parcels":
        script = f"""
from app.db.session import SessionLocal
from app.db.models import Parcel
from parking_ingestion.address_normalize import normalize_parcel_address_props
from sqlalchemy import select

cf = {county_fips!r}
limit = {limit}
updated = 0
with SessionLocal() as db:
    rows = db.scalars(select(Parcel).where(Parcel.county_fips == cf).limit(limit)).all()
    for p in rows:
        props = dict(p.raw_properties or {{}})
        if normalize_parcel_address_props(props, county_fips=cf):
            p.raw_properties = props
            updated += 1
    db.commit()
print({{"normalized": updated, "county_fips": cf}})
"""
        return {"action": "normalize_watech_raw_properties", "source_id": sid, "result": _compose_exec(script)}

    if sid == "nominatim_centroid_fallback":
        result = _api_post(
            f"/internal/metrics/backfill-wa-centroid-addresses?limit={limit}&county_fips={county_fips}"
        )
        return {"action": "wa_centroid_geocode_backfill", "source_id": sid, "result": result}

    if sid in ARCGIS_ADDRESS_SOURCES:
        return {
            "action": "wa_arcgis_parcel_address_backfill",
            "source_id": sid,
            "result": _compose_exec(_arcgis_backfill_snippet(sid, county_fips, limit)),
        }

    if sid.endswith("_assessor_roll"):
        return {
            "action": "assessor_roll_merge",
            "source_id": sid,
            "status": "needs_connector",
            "detail": (
                f"Add ArcGIS/assessor merge for {sid} in connectors.py and source_catalog.csv; "
                "rotation recorded in field maps."
            ),
        }

    return {"action": "unknown", "source_id": sid, "status": "skipped"}
