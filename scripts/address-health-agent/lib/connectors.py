"""Dispatch address source actions — extend here when adding a new scraper/merge path."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .paths import REPO_ROOT as ROOT


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


def run_connector(source_id: str, *, county_fips: str, limit: int = 250) -> dict[str, Any]:
    """Run the best available action for a catalog source_id."""
    sid = source_id.strip()

    if sid in ("baltimore_realproperty", "baltimore_address_points"):
        result = _api_post(f"/internal/metrics/backfill-baltimore-addresses?limit={limit}&dry_run=false")
        return {"action": "baltimore_address_backfill", "source_id": sid, "result": result}

    if sid == "watech_statewide_parcels":
        script = """
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models import Parcel
from parking_ingestion.address_normalize import normalize_parcel_address_props
from sqlalchemy import select

cf = %r
limit = %d
updated = 0
with SessionLocal() as db:
    rows = db.scalars(select(Parcel).where(Parcel.county_fips == cf).limit(limit)).all()
    for p in rows:
        props = dict(p.raw_properties or {})
        if normalize_parcel_address_props(props, county_fips=cf):
            p.raw_properties = props
            updated += 1
    db.commit()
print({"normalized": updated, "county_fips": cf})
""" % (
            county_fips,
            limit,
        )
        return {"action": "normalize_watech_raw_properties", "source_id": sid, "result": _compose_exec(script)}

    if sid == "nominatim_centroid_fallback":
        result = _api_post(
            f"/internal/metrics/backfill-wa-centroid-addresses?limit={limit}&county_fips={county_fips}"
        )
        return {"action": "wa_centroid_geocode_backfill", "source_id": sid, "result": result}

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
