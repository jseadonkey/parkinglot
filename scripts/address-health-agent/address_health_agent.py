#!/usr/bin/env python3
"""12h address health review — measure coverage, rotate catalog sources, run connectors."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "api"))
sys.path.insert(0, str(ROOT / "scripts" / "address-health-agent"))

from lib.catalog_sync import apply_source_rotation  # noqa: E402
from lib.chains import advance_source, source_chain_for_county  # noqa: E402
from lib.connectors import run_connector  # noqa: E402
from lib.metrics import baltimore_candidate_coverage, county_candidate_address_coverage  # noqa: E402
from lib.paths import AGENT_DATA, ROLLOUT_PLAN, SNAPSHOT_FILE, STATE_FILE  # noqa: E402


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def active_county_fips() -> list[str]:
    plan = _load_yaml(ROLLOUT_PLAN)
    waves = plan.get("waves") if isinstance(plan.get("waves"), list) else []
    out: list[str] = []
    for wave in waves:
        if not isinstance(wave, dict) or not wave.get("active"):
            continue
        fips = wave.get("county_fips")
        if isinstance(fips, list):
            out.extend(str(f).strip() for f in fips if str(f).strip())
    return out


def policy() -> dict[str, Any]:
    plan = _load_yaml(ROLLOUT_PLAN)
    pol = plan.get("policy") if isinstance(plan.get("policy"), dict) else {}
    return {
        "min_candidate_address_pct": float(pol.get("min_candidate_address_pct") or 35),
        "min_parcels_loaded": int(pol.get("min_parcels_loaded") or 50),
        "stagnation_hours": float(pol.get("stagnation_hours") or 12),
        "max_rotations_per_week": int(pol.get("max_rotations_per_week") or 3),
    }


def _hours_since(iso_ts: str | None) -> float | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except ValueError:
        return None


def _should_rotate(
    county_fips: str,
    metric: dict[str, Any],
    state: dict[str, Any],
    pol: dict[str, Any],
    previous_snapshot: dict[str, Any] | None,
) -> tuple[bool, str]:
    pct = float(metric.get("candidate_address_pct") or 0)
    loaded = int(metric.get("parcels_loaded") or 0)
    if loaded < int(pol["min_parcels_loaded"]):
        return False, "insufficient_parcels_loaded"
    if pct >= float(pol["min_candidate_address_pct"]):
        return False, "coverage_ok"

    county_state = state.get(county_fips) if isinstance(state.get(county_fips), dict) else {}
    rotations = int(county_state.get("rotations_this_week") or 0)
    if rotations >= int(pol["max_rotations_per_week"]):
        return False, "max_rotations_per_week"

    prev_pct = None
    if previous_snapshot:
        for row in previous_snapshot.get("counties") or []:
            if isinstance(row, dict) and row.get("county_fips") == county_fips:
                prev_pct = float(row.get("candidate_address_pct") or 0)
                break

    last_improved = county_state.get("last_improved_at")
    last_rotated = county_state.get("last_rotated_at")
    stagnation_h = float(pol["stagnation_hours"])

    if prev_pct is not None and pct > prev_pct:
        return False, "improving"

    if last_rotated and (_hours_since(str(last_rotated)) or 0) < stagnation_h:
        return False, "cooldown_after_rotation"

    if prev_pct is not None and pct <= prev_pct and (_hours_since(str(last_improved)) or stagnation_h) >= stagnation_h:
        return True, "stagnant_below_threshold"

    if prev_pct is None and (_hours_since(str(last_improved)) or stagnation_h) >= stagnation_h:
        return True, "first_check_below_threshold"

    return False, "waiting_for_stagnation_window"


def run_agent(*, write_snapshot: bool = True, remediate: bool = True) -> dict[str, Any]:
    from app.db.session import SessionLocal

    pol = policy()
    counties = active_county_fips()
    state = _load_json(STATE_FILE)
    previous = _load_json(SNAPSHOT_FILE)
    rotations: list[dict[str, Any]] = []
    connector_runs: list[dict[str, Any]] = []
    county_metrics: list[dict[str, Any]] = []

    with SessionLocal() as db:
        for fips in counties:
            if fips == "24510":
                metric = baltimore_candidate_coverage(db)
            else:
                metric = county_candidate_address_coverage(db, fips)
            county_metrics.append(metric)

            rotate, reason = _should_rotate(fips, metric, state, pol, previous)
            county_state = dict(state.get(fips) or {})
            county_state["active_source_id"] = county_state.get("active_source_id") or (
                source_chain_for_county(fips)[0] if source_chain_for_county(fips) else None
            )
            county_state["last_checked_at"] = datetime.now(timezone.utc).isoformat()
            county_state["last_coverage_pct"] = metric.get("candidate_address_pct")
            county_state["last_reason"] = reason

            prev_row_pct = None
            for row in previous.get("counties") or []:
                if isinstance(row, dict) and row.get("county_fips") == fips:
                    prev_row_pct = float(row.get("candidate_address_pct") or 0)
                    break
            cur_pct = float(metric.get("candidate_address_pct") or 0)
            if prev_row_pct is not None and cur_pct > prev_row_pct:
                county_state["last_improved_at"] = datetime.now(timezone.utc).isoformat()
            elif "last_improved_at" not in county_state:
                county_state["last_improved_at"] = datetime.now(timezone.utc).isoformat()

            if rotate and remediate:
                current = str(county_state.get("active_source_id") or "")
                nxt, did_rotate = advance_source(fips, current or None)
                if did_rotate and nxt:
                    sync = apply_source_rotation(fips, nxt)
                    county_state["active_source_id"] = nxt
                    county_state["last_rotated_at"] = datetime.now(timezone.utc).isoformat()
                    county_state["rotations_this_week"] = int(county_state.get("rotations_this_week") or 0) + 1
                    conn = run_connector(nxt, county_fips=fips, limit=250)
                    rotations.append(
                        {
                            "county_fips": fips,
                            "from": current,
                            "to": nxt,
                            "reason": reason,
                            "catalog_sync": sync,
                        }
                    )
                    connector_runs.append(conn)
                elif not nxt:
                    county_state["chain_exhausted"] = True
                    connector_runs.append(
                        {
                            "county_fips": fips,
                            "status": "needs_new_source",
                            "detail": "Add source to address_source_chains.yaml and source_catalog.csv",
                        }
                    )
            elif remediate and reason in ("first_check_below_threshold", "stagnant_below_threshold"):
                active = str(county_state.get("active_source_id") or "")
                if active:
                    connector_runs.append(run_connector(active, county_fips=fips, limit=100))

            state[fips] = county_state

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "policy": pol,
        "active_counties": counties,
        "counties": county_metrics,
        "rotations": rotations,
        "connector_runs": connector_runs,
        "state": state,
    }

    if write_snapshot:
        _save_json(STATE_FILE, state)
        _save_json(SNAPSHOT_FILE, report)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Address health agent")
    parser.add_argument("--write-snapshot", action="store_true", default=True)
    parser.add_argument("--skip-remediate", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run_agent(write_snapshot=args.write_snapshot, remediate=not args.skip_remediate)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(json.dumps({"rotations": report["rotations"], "counties": report["counties"]}, indent=2))

    if report.get("rotations"):
        return 0
    needs = [c for c in report.get("connector_runs") or [] if c.get("status") == "needs_new_source"]
    return 1 if needs else 0


if __name__ == "__main__":
    raise SystemExit(main())
