"""Operator-facing ingest / scoring backlog status (Celery + candidate GeoJSON vs DB)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.celery_app import celery
from app.db.models import Parcel, ParcelScore
from app.pilot_scope_filter import parcel_in_scope_clause
from app.scoring_profiles import ENTITLEMENT

logger = logging.getLogger(__name__)

DEFAULT_CANDIDATE_PATH = Path("/app/data/pilot/kent_pilot_candidates.geojson")

_feature_count_cache: tuple[float, int] | None = None


def _cached_feature_count(path: Path) -> int | None:
    global _feature_count_cache
    if not path.is_file():
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _feature_count_cache is not None and _feature_count_cache[0] == mtime:
        return _feature_count_cache[1]
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        n = len(data.get("features") or [])
        _feature_count_cache = (mtime, n)
        return n
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("ingest_status: could not read feature count from %s: %s", path, exc)
        return None


def _active_ingest_geojson_tasks() -> list[dict[str, Any]]:
    try:
        inspector = celery.control.inspect(timeout=2.0)
        active = inspector.active() if inspector else None
    except Exception as exc:
        logger.warning("ingest_status: celery inspect failed: %s", exc)
        return []
    if not active:
        return []
    out: list[dict[str, Any]] = []
    for _worker, tasks in active.items():
        for task in tasks or []:
            if task.get("name") == "app.tasks.ingest_geojson_path":
                out.append(task)
    return out


@dataclass(frozen=True)
class IngestStatusSnapshot:
    ingest_active: bool
    active_ingest_task_id: str | None
    active_ingest_path: str | None
    candidate_geojson_path: str
    candidate_feature_count: int | None
    parcels_total_db: int
    parcels_in_scope_db: int
    parcels_with_entitlement_score: int
    phase: str
    headline: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ingest_active": self.ingest_active,
            "active_ingest_task_id": self.active_ingest_task_id,
            "active_ingest_path": self.active_ingest_path,
            "candidate_geojson_path": self.candidate_geojson_path,
            "candidate_feature_count": self.candidate_feature_count,
            "parcels_total_db": self.parcels_total_db,
            "parcels_in_scope_db": self.parcels_in_scope_db,
            "parcels_with_entitlement_score": self.parcels_with_entitlement_score,
            "phase": self.phase,
            "headline": self.headline,
            "detail": self.detail,
        }


def build_ingest_status_snapshot(
    db: Session,
    *,
    candidate_path: Path | None = None,
) -> IngestStatusSnapshot:
    path = candidate_path or DEFAULT_CANDIDATE_PATH
    active = _active_ingest_geojson_tasks()
    ingest_active = bool(active)
    task_id = str(active[0]["id"]) if active else None
    ingest_path = None
    if active:
        args = active[0].get("args") or ()
        if args:
            ingest_path = str(args[0])

    candidate_n = _cached_feature_count(path)

    parcels_total = int(db.scalar(select(func.count()).select_from(Parcel)) or 0)
    parcels_in_scope = int(
        db.scalar(select(func.count()).select_from(Parcel).where(parcel_in_scope_clause())) or 0
    )
    ent_sub = (
        select(func.count(func.distinct(ParcelScore.parcel_id)))
        .where(ParcelScore.score_profile == ENTITLEMENT)
        .scalar_subquery()
    )
    parcels_with_ent = int(db.scalar(select(ent_sub)) or 0)

    if ingest_active:
        target = f"{candidate_n:,}" if candidate_n is not None else "the full candidate list"
        return IngestStatusSnapshot(
            ingest_active=True,
            active_ingest_task_id=task_id,
            active_ingest_path=ingest_path,
            candidate_geojson_path=str(path),
            candidate_feature_count=candidate_n,
            parcels_total_db=parcels_total,
            parcels_in_scope_db=parcels_in_scope,
            parcels_with_entitlement_score=parcels_with_ent,
            phase="ingesting",
            headline="Parcel load in progress",
            detail=(
                f"The system is importing {target} pre-filtered lots into the database. "
                f"Parcels in DB still shows {parcels_in_scope:,} until this job finishes and commits "
                f"(typically hours). Entitlement and strategic scores will rise gradually afterward (often days)."
            ),
        )

    pending_ingest = (
        candidate_n is not None
        and candidate_n > max(parcels_in_scope + 500, 1000)
        and candidate_n > int(parcels_in_scope * 1.2)
    )
    if pending_ingest:
        return IngestStatusSnapshot(
            ingest_active=False,
            active_ingest_task_id=None,
            active_ingest_path=None,
            candidate_geojson_path=str(path),
            candidate_feature_count=candidate_n,
            parcels_total_db=parcels_total,
            parcels_in_scope_db=parcels_in_scope,
            parcels_with_entitlement_score=parcels_with_ent,
            phase="ingest_pending",
            headline="Candidate file ready — load not reflected in DB yet",
            detail=(
                f"{candidate_n:,} lots are in the candidate file but only {parcels_in_scope:,} are in the database. "
                "If this persists, re-run scripts/run_pilot_parcel_ingest.sh or check worker logs."
            ),
        )

    scoring_backlog = parcels_in_scope > 100 and parcels_with_ent < int(parcels_in_scope * 0.85)
    if scoring_backlog:
        return IngestStatusSnapshot(
            ingest_active=False,
            active_ingest_task_id=None,
            active_ingest_path=None,
            candidate_geojson_path=str(path),
            candidate_feature_count=candidate_n,
            parcels_total_db=parcels_total,
            parcels_in_scope_db=parcels_in_scope,
            parcels_with_entitlement_score=parcels_with_ent,
            phase="scoring_backlog",
            headline="Scoring backlog in progress",
            detail=(
                f"{parcels_with_ent:,} of {parcels_in_scope:,} in-scope parcels have entitlement scores. "
                "The worker processes the queue automatically — refresh this page to watch counts climb."
            ),
        )

    return IngestStatusSnapshot(
        ingest_active=False,
        active_ingest_task_id=None,
        active_ingest_path=None,
        candidate_geojson_path=str(path),
        candidate_feature_count=candidate_n,
        parcels_total_db=parcels_total,
        parcels_in_scope_db=parcels_in_scope,
        parcels_with_entitlement_score=parcels_with_ent,
        phase="idle",
        headline="No bulk ingest running",
        detail="Counts reflect the current database. Use Parcels and Outreach when ready.",
    )
