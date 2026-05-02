"""Queries for same-owner parcel rollup (normalized_owner_key + latest entitlement score)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from app.db.models import OwnerCandidateRow, Parcel, ParcelScore
from app.scoring_profiles import ENTITLEMENT


def _latest_scores_subquery(profile: str) -> Any:
    agg = (
        select(
            ParcelScore.parcel_id.label("parcel_id"),
            func.max(ParcelScore.created_at).label("mx"),
        )
        .where(ParcelScore.score_profile == profile)
        .group_by(ParcelScore.parcel_id)
    ).subquery()
    return (
        select(ParcelScore.parcel_id.label("parcel_id"), ParcelScore.total_score.label("total_score"))
        .join(
            agg,
            and_(
                ParcelScore.parcel_id == agg.c.parcel_id,
                ParcelScore.created_at == agg.c.mx,
                ParcelScore.score_profile == profile,
            ),
        )
    ).subquery()


def count_qualified_peer_parcels(
    db: Session,
    *,
    parcel_id: uuid.UUID,
    normalized_owner_key: str,
    entitlement_floor: float,
    profile: str = ENTITLEMENT,
    sample_limit: int = 15,
) -> tuple[int, list[str]]:
    """Peers sharing ``normalized_owner_key`` with latest ``profile`` score ≥ ``entitlement_floor``.

    Returns (count excluding ``parcel_id``, sample labels ``county_fips / apn``).
    """
    ls = _latest_scores_subquery(profile).alias("ls")

    peer_ids_sub = (
        select(Parcel.id.label("pid"))
        .select_from(OwnerCandidateRow)
        .join(Parcel, OwnerCandidateRow.parcel_id == Parcel.id)
        .join(ls, ls.c.parcel_id == Parcel.id)
        .where(OwnerCandidateRow.normalized_owner_key == normalized_owner_key)
        .where(Parcel.id != parcel_id)
        .where(ls.c.total_score >= entitlement_floor)
        .distinct()
        .subquery()
    )
    total = db.scalar(select(func.count()).select_from(peer_ids_sub))
    n_peers = int(total or 0)

    sample_stmt: Select[tuple[Any, ...]] = (
        select(Parcel.county_fips, Parcel.apn)
        .select_from(OwnerCandidateRow)
        .join(Parcel, OwnerCandidateRow.parcel_id == Parcel.id)
        .join(ls, ls.c.parcel_id == Parcel.id)
        .where(OwnerCandidateRow.normalized_owner_key == normalized_owner_key)
        .where(Parcel.id != parcel_id)
        .where(ls.c.total_score >= entitlement_floor)
        .distinct()
        .order_by(Parcel.county_fips, Parcel.apn)
        .limit(sample_limit)
    )
    rows = db.execute(sample_stmt).all()
    examples = [f"{r.county_fips} / {r.apn}" for r in rows]
    return n_peers, examples


def list_peer_parcel_summaries(
    db: Session,
    *,
    normalized_owner_key: str,
    entitlement_floor: float,
    profile: str = ENTITLEMENT,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """All qualified parcels for key (including multiple rows per parcel — dedupe by parcel id)."""
    ls = _latest_scores_subquery(profile).alias("ls")
    stmt = (
        select(Parcel.id, Parcel.apn, Parcel.county_fips, ls.c.total_score)
        .select_from(OwnerCandidateRow)
        .join(Parcel, OwnerCandidateRow.parcel_id == Parcel.id)
        .join(ls, ls.c.parcel_id == Parcel.id)
        .where(OwnerCandidateRow.normalized_owner_key == normalized_owner_key)
        .where(ls.c.total_score >= entitlement_floor)
        .order_by(ls.c.total_score.desc(), Parcel.county_fips, Parcel.apn)
        .limit(max(limit * 4, limit))
    )
    out: list[dict[str, Any]] = []
    seen: set[uuid.UUID] = set()
    for pid, apn, cfips, tot in db.execute(stmt).all():
        if pid in seen:
            continue
        seen.add(pid)
        out.append(
            {
                "parcel_id": str(pid),
                "apn": apn,
                "county_fips": cfips,
                "latest_entitlement_score": float(tot),
            }
        )
        if len(out) >= limit:
            break
    return out


def rank_owner_portfolios(
    db: Session,
    *,
    entitlement_floor: float,
    min_peers: int = 2,
    limit: int = 50,
    profile: str = ENTITLEMENT,
) -> list[dict[str, Any]]:
    """Owner keys with at least ``min_peers`` qualified parcels (latest entitlement ≥ floor)."""
    ls = _latest_scores_subquery(profile).alias("ls")
    qualified_parcels = (
        select(Parcel.id.label("pid"))
        .join(ls, ls.c.parcel_id == Parcel.id)
        .where(ls.c.total_score >= entitlement_floor)
        .distinct()
        .subquery()
    )
    cnt = func.count(func.distinct(Parcel.id)).label("cnt")
    stmt = (
        select(OwnerCandidateRow.normalized_owner_key.label("nk"), cnt)
        .select_from(OwnerCandidateRow)
        .join(Parcel, OwnerCandidateRow.parcel_id == Parcel.id)
        .join(qualified_parcels, qualified_parcels.c.pid == Parcel.id)
        .where(OwnerCandidateRow.normalized_owner_key.isnot(None))
        .group_by(OwnerCandidateRow.normalized_owner_key)
        .having(cnt >= min_peers)
        .order_by(cnt.desc())
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    out_pg: list[dict[str, Any]] = []
    for row in rows:
        nk = row[0]
        cnt = row[1]
        out_pg.append({"normalized_owner_key": nk, "qualified_parcel_count": int(cnt)})
    return out_pg
