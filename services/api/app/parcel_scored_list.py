"""Parcels with latest Atlas / Beacon / Cartographer scores for operator list views."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import case, desc, func, nulls_last, select
from sqlalchemy.orm import Session

from app.db.models import Parcel, ParcelScore
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC
from app.zoning_entitlement import (
    baltimore_zone_codes_for_tier,
    effective_zoning_code,
    parcel_zoning_symbol,
    parcel_zoning_tier,
)

ParcelSortProfile = Literal["combined", "entitlement", "strategic", "identification"]
ZoningTierFilter = Literal["permitted", "conditional", "council", "excluded"]
COMBINED: str = "combined"


@dataclass(frozen=True)
class ParcelScoredRowData:
    parcel_id: uuid.UUID
    apn: str
    county_fips: str
    zoning_code: str | None
    lot_sqft: float | None
    zoning_principal_use_symbol: str | None
    zoning_entitlement_tier: str | None
    entitlement_score: float | None
    strategic_score: float | None
    identification_score: float | None
    combined_score: float | None
    created_at: datetime
    situs_address: str | None = None
    mailing_address: str | None = None


def _combined_score_value(
    entitlement: float | None,
    strategic: float | None,
    identification: float | None,
) -> float | None:
    parts = [x for x in (entitlement, strategic, identification) if x is not None]
    if not parts:
        return None
    return sum(parts) / len(parts)


def _combined_score_sql(ent_sub: Any, str_sub: Any, id_sub: Any) -> Any:
    """Average of non-null Atlas / Beacon / Cartographer scores (for ORDER BY)."""
    n = (
        case((ent_sub.isnot(None), 1), else_=0)
        + case((str_sub.isnot(None), 1), else_=0)
        + case((id_sub.isnot(None), 1), else_=0)
    )
    total = func.coalesce(ent_sub, 0) + func.coalesce(str_sub, 0) + func.coalesce(id_sub, 0)
    return total / func.nullif(n, 0)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_prop(raw_properties: dict[str, Any] | None, keys: tuple[str, ...]) -> str | None:
    props = raw_properties or {}
    for key in keys:
        value = _clean_text(props.get(key))
        if value:
            return value
    return None


def _first_brief_contact(brief: dict[str, Any] | None, kind: str) -> str | None:
    if not isinstance(brief, dict):
        return None
    guess = _clean_text(brief.get(f"{kind}_guess"))
    if guess:
        return guess
    raw_contacts = brief.get("contact_points")
    if not isinstance(raw_contacts, list):
        return None
    for item in raw_contacts:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").strip() != kind:
            continue
        value = _clean_text(item.get("value"))
        if value:
            return value
    return None


def _situs_address(raw_properties: dict[str, Any] | None, brief: dict[str, Any] | None) -> str | None:
    return _first_prop(
        raw_properties,
        (
            "PROPERTY_ADDRESS",
            "property_address",
            "SITUS_ADDRESS",
            "situs_address",
            "SITUS_ADDR",
            "situs_addr",
            "ADDR_FULL",
            "addr_full",
            "FULLADDR",
            "fulladdr",
        ),
    ) or _first_brief_contact(brief, "situs_address")


def _mailing_address(raw_properties: dict[str, Any] | None, brief: dict[str, Any] | None) -> str | None:
    return _first_prop(
        raw_properties,
        (
            "MAILING_ADDRESS",
            "mailing_address",
            "MAIL_ADDR",
            "mail_addr",
            "MAILTOADD",
            "mailtoadd",
            "OWNER_MAILING",
            "owner_mailing",
            "FULL_MAILING",
            "full_mailing",
        ),
    ) or _first_brief_contact(brief, "mailing_address")


def _latest_score_subq(parcel_id_col: Any, profile: str) -> Any:
    return (
        select(ParcelScore.total_score)
        .where(ParcelScore.parcel_id == parcel_id_col)
        .where(ParcelScore.score_profile == profile)
        .order_by(desc(ParcelScore.created_at))
        .limit(1)
        .correlate(Parcel)
        .scalar_subquery()
    )


def _parcel_scope_subq(
    *,
    county_fips: str,
    state_fips: str,
    zoning_tier: str,
) -> Any:
    scope = select(Parcel.id.label("parcel_id"))
    if county_fips:
        scope = scope.where(Parcel.county_fips == county_fips)
    elif state_fips:
        scope = scope.where(Parcel.county_fips.startswith(state_fips))
    if zoning_tier in ("permitted", "conditional", "council", "excluded"):
        codes = baltimore_zone_codes_for_tier(zoning_tier)
        if not codes:
            return None
        # Baltimore-only filter until WA rules carry principal_use_symbol entries.
        scope = scope.where(Parcel.county_fips == "24510", func.upper(Parcel.zoning_code).in_(sorted(codes)))
    return scope.subquery()


def _latest_scores_pivot_subq(parcel_scope: Any) -> Any:
    ranked = (
        select(
            ParcelScore.parcel_id.label("parcel_id"),
            ParcelScore.score_profile.label("score_profile"),
            ParcelScore.total_score.label("total_score"),
            func.row_number()
            .over(
                partition_by=(ParcelScore.parcel_id, ParcelScore.score_profile),
                order_by=ParcelScore.created_at.desc(),
            )
            .label("rn"),
        )
        .join(parcel_scope, ParcelScore.parcel_id == parcel_scope.c.parcel_id)
        .where(ParcelScore.score_profile.in_((ENTITLEMENT, STRATEGIC, IDENTIFICATION)))
        .subquery()
    )
    return (
        select(
            ranked.c.parcel_id,
            func.max(ranked.c.total_score).filter(ranked.c.score_profile == ENTITLEMENT).label("ent_score"),
            func.max(ranked.c.total_score).filter(ranked.c.score_profile == STRATEGIC).label("str_score"),
            func.max(ranked.c.total_score).filter(ranked.c.score_profile == IDENTIFICATION).label("id_score"),
        )
        .where(ranked.c.rn == 1)
        .group_by(ranked.c.parcel_id)
        .subquery()
    )


def query_parcels_scored_list(
    db: Session,
    *,
    limit: int,
    sort: ParcelSortProfile = COMBINED,
    county_fips: str | None = None,
    state_fips: str | None = None,
    zoning_tier: str | None = None,
    min_entitlement_score: float | None = None,
) -> list[ParcelScoredRowData]:
    """All parcels with latest score per profile, ordered by ``sort`` (null scores last)."""
    cap = min(max(limit, 1), 2000)
    cf = (county_fips or "").strip()
    st = (state_fips or "").strip()
    tier = (zoning_tier or "").strip().lower()
    parcel_scope = _parcel_scope_subq(county_fips=cf, state_fips=st, zoning_tier=tier)
    if parcel_scope is None:
        return []
    latest_scores = _latest_scores_pivot_subq(parcel_scope)
    ent_sub = latest_scores.c.ent_score
    str_sub = latest_scores.c.str_score
    id_sub = latest_scores.c.id_score

    combined_sub = _combined_score_sql(ent_sub, str_sub, id_sub)
    sort_col = combined_sub
    if sort == ENTITLEMENT:
        sort_col = ent_sub
    elif sort == STRATEGIC:
        sort_col = str_sub
    elif sort == IDENTIFICATION:
        sort_col = id_sub

    stmt = select(
        Parcel.id,
        Parcel.apn,
        Parcel.county_fips,
        Parcel.zoning_code,
        Parcel.raw_properties,
        Parcel.owner_outreach_brief,
        Parcel.lot_sqft,
        Parcel.created_at,
        ent_sub.label("ent_score"),
        str_sub.label("str_score"),
        id_sub.label("id_score"),
    ).outerjoin(latest_scores, Parcel.id == latest_scores.c.parcel_id)
    if cf:
        stmt = stmt.where(Parcel.county_fips == cf)
    elif st:
        stmt = stmt.where(Parcel.county_fips.startswith(st))
    if tier in ("permitted", "conditional", "council", "excluded"):
        codes = baltimore_zone_codes_for_tier(tier)
        if codes:
            stmt = stmt.where(Parcel.county_fips == "24510", func.upper(Parcel.zoning_code).in_(sorted(codes)))
        else:
            return []
    if min_entitlement_score is not None:
        stmt = stmt.where(ent_sub.isnot(None), ent_sub >= float(min_entitlement_score))
    stmt = stmt.order_by(nulls_last(desc(sort_col)), desc(Parcel.created_at)).limit(cap)
    out: list[ParcelScoredRowData] = []
    for r in db.execute(stmt).all():
        pid, apn, cfips, zoning, raw_props, brief, sqft, created, ent_f, str_f, id_f = r
        ent_f = float(ent_f) if ent_f is not None else None
        str_f = float(str_f) if str_f is not None else None
        id_f = float(id_f) if id_f is not None else None
        raw_dict = raw_props if isinstance(raw_props, dict) else None
        brief_dict = brief if isinstance(brief, dict) else None
        z_code = effective_zoning_code(zoning, raw_dict)
        symbol = parcel_zoning_symbol(county_fips=cfips, zoning_code=z_code, raw_properties=raw_dict)
        ent_tier = parcel_zoning_tier(county_fips=cfips, zoning_code=z_code, raw_properties=raw_dict)
        out.append(
            ParcelScoredRowData(
                parcel_id=pid,
                apn=apn,
                county_fips=cfips,
                situs_address=_situs_address(raw_dict, brief_dict),
                mailing_address=_mailing_address(raw_dict, brief_dict),
                zoning_code=z_code,
                lot_sqft=float(sqft) if sqft is not None else None,
                zoning_principal_use_symbol=symbol,
                zoning_entitlement_tier=ent_tier,
                entitlement_score=ent_f,
                strategic_score=str_f,
                identification_score=id_f,
                combined_score=_combined_score_value(ent_f, str_f, id_f),
                created_at=created,
            ),
        )
    return out
