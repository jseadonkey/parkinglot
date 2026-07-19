"""Parcels with latest Atlas / Beacon / Cartographer scores for operator list views."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Float, and_, case, cast, desc, func, inspect, literal, nulls_last, or_, select
from sqlalchemy.orm import Session

from app.db.models import Parcel, ParcelScore
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC
from app.zoning_entitlement import (
    curated_zone_codes_for_tier,
    effective_zoning_code,
    parcel_zoning_symbol,
    parcel_zoning_tier,
)
from parking_core.suitability import (
    UNDERUTILIZED_MAX_IMPROVEMENT_RATIO,
    compute_parcel_suitability,
)
from parking_core.waza_provisional import PROVISIONAL_WAZA_GENERAL

SuitabilityFilter = Literal["vacant", "underutilized", "vacant_or_underutilized"]

_NUMERIC_RE = r"^[0-9]+(\.[0-9]+)?$"


def _json_num(key: str) -> Any:
    """Safe numeric read of ``raw_properties[key]`` (NULL when non-numeric)."""
    txt = func.nullif(func.replace(Parcel.raw_properties[key].astext, ",", ""), "")
    return case((txt.op("~")(_NUMERIC_RE), cast(txt, Float)), else_=None)


def _suitability_where(suitability: str) -> Any | None:
    """SQL predicate over ``raw_properties`` assessor value fields (best with a county filter)."""
    s = (suitability or "").strip().lower()
    if s not in ("vacant", "underutilized", "vacant_or_underutilized"):
        return None
    bldg = _json_num("VALUE_BLDG")
    land = _json_num("VALUE_LAND")
    use_txt = func.upper(func.coalesce(Parcel.raw_properties["LANDUSE_CD"].astext, ""))
    vacant = or_(
        and_(bldg.isnot(None), bldg <= 0, land.isnot(None), land > 0),
        use_txt.like("%VACANT%"),
    )
    underutil = and_(
        bldg.isnot(None),
        bldg > 0,
        land.isnot(None),
        land > 0,
        (bldg / (bldg + land)) <= UNDERUTILIZED_MAX_IMPROVEMENT_RATIO,
    )
    if s == "vacant":
        return vacant
    if s == "underutilized":
        return underutil
    return or_(vacant, underutil)

ParcelSortProfile = Literal["combined", "entitlement", "strategic", "identification"]
ZoningTierFilter = Literal["permitted", "conditional", "provisional", "council", "excluded"]
COMBINED: str = "combined"


def _zoning_tier_where(zoning_tier: str) -> Any | None:
    """SQL predicate for curated zone codes or WAZA provisional COM/MXU/IND."""
    tier = (zoning_tier or "").strip().lower()
    if tier == "provisional":
        zg = func.upper(func.coalesce(Parcel.raw_properties["WAZAZoneGeneral"].astext, ""))
        return zg.in_(sorted(PROVISIONAL_WAZA_GENERAL))
    if tier in ("permitted", "conditional", "council", "excluded"):
        codes = curated_zone_codes_for_tier(tier)
        if not codes:
            return None
        return func.upper(Parcel.zoning_code).in_(sorted(codes))
    if tier in ("prospect", "prospects"):
        # Human shortlist: curated P/CB/M or WAZA commercial-class provisional.
        codes = curated_zone_codes_for_tier("permitted") | curated_zone_codes_for_tier("conditional")
        zg = func.upper(func.coalesce(Parcel.raw_properties["WAZAZoneGeneral"].astext, ""))
        parts: list[Any] = [zg.in_(sorted(PROVISIONAL_WAZA_GENERAL))]
        if codes:
            parts.append(func.upper(Parcel.zoning_code).in_(sorted(codes)))
        return or_(*parts)
    return None


def _parcel_column_exists(db: Session, column: str) -> bool:
    try:
        cols = inspect(db.get_bind()).get_columns("parcels")
    except Exception:
        return False
    return any(c.get("name") == column for c in cols)


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
    suitability: str | None = None
    is_vacant_land: bool | None = None
    improvement_ratio: float | None = None


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
    tier_where = _zoning_tier_where(zoning_tier)
    if zoning_tier and tier_where is None and zoning_tier.strip().lower() not in ("",):
        # Explicit tier with no matching codes → empty result.
        if zoning_tier.strip().lower() in (
            "permitted",
            "conditional",
            "provisional",
            "council",
            "excluded",
            "prospect",
            "prospects",
        ):
            return None
    if tier_where is not None:
        scope = scope.where(tier_where)
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
    suitability: str | None = None,
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

    has_owner_brief_col = _parcel_column_exists(db, "owner_outreach_brief")
    brief_col = (
        Parcel.owner_outreach_brief
        if has_owner_brief_col
        else literal(None).label("owner_outreach_brief")
    )

    stmt = select(
        Parcel.id,
        Parcel.apn,
        Parcel.county_fips,
        Parcel.zoning_code,
        Parcel.raw_properties,
        brief_col,
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
    tier_where = _zoning_tier_where(tier)
    if tier and tier_where is None and tier in (
        "permitted",
        "conditional",
        "provisional",
        "council",
        "excluded",
        "prospect",
        "prospects",
    ):
        return []
    if tier_where is not None:
        stmt = stmt.where(tier_where)
    if min_entitlement_score is not None:
        stmt = stmt.where(ent_sub.isnot(None), ent_sub >= float(min_entitlement_score))
    suit_where = _suitability_where(suitability or "")
    if suit_where is not None:
        stmt = stmt.where(suit_where)
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
        suit = compute_parcel_suitability(raw_dict)
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
                suitability=suit["suitability"],
                is_vacant_land=suit["is_vacant_land"],
                improvement_ratio=suit["improvement_ratio"],
            ),
        )
    return out
