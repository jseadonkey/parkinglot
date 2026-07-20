"""Parcels with latest Atlas / Beacon / Cartographer scores for operator list views."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Float, and_, case, cast, desc, func, inspect, literal, nulls_last, or_, select, text
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

# King Present Use codes that are not buildable lots (must stay in sync with
# parking_core.suitability._KING_NON_DEVELOPABLE_PRESENT_USE).
_NON_DEVELOPABLE_LANDUSE_CDS = (
    "149",
    "150",
    "266",
    "267",
    "323",
    "324",
    "325",
    "326",
    "327",
    "328",
    "330",
    "331",
    "332",
    "333",
    "334",
    "335",
    "336",
    "337",
)

SuitabilityFilter = Literal["vacant", "underutilized", "vacant_or_underutilized"]

_NUMERIC_RE = r"^[0-9]+(\.[0-9]+)?$"


def _json_num(key: str) -> Any:
    """Safe numeric read of ``raw_properties[key]`` (NULL when non-numeric)."""
    txt = func.nullif(func.replace(Parcel.raw_properties[key].astext, ",", ""), "")
    return case((txt.op("~")(_NUMERIC_RE), cast(txt, Float)), else_=None)


def _suitability_where(suitability: str) -> Any | None:
    """SQL predicate over ``raw_properties`` assessor value fields (best with a county filter)."""
    s = (suitability or "").strip().lower()
    if s not in (
        "vacant",
        "underutilized",
        "vacant_or_underutilized",
        "existing_parking",
        "not_existing_parking",
    ):
        return None
    bldg = _json_num("VALUE_BLDG")
    land = _json_num("VALUE_LAND")
    dor = func.nullif(func.btrim(Parcel.raw_properties["LANDUSE_CD"].astext), "")
    orig = func.coalesce(Parcel.raw_properties["ORIG_LANDUSE_CD"].astext, "")
    use_txt = func.upper(func.coalesce(Parcel.raw_properties["LANDUSE_CD"].astext, ""))
    # WA DOR 46; King Present Use 159/180/182 (often stored directly in LANDUSE_CD);
    # plus common parking phrases.
    existing_parking = or_(
        dor == "46",
        dor.in_(("159", "180", "182")),
        orig.op("~")(r"(^|-)(159|180|182)$"),
        use_txt.like("%AUTOMOBILE PARKING%"),
        use_txt.like("%PARKING LOT%"),
        use_txt.like("%COMMERCIAL PARKING%"),
        use_txt.like("%PARKING GARAGE%"),
    )
    non_developable = or_(
        dor.in_(_NON_DEVELOPABLE_LANDUSE_CDS),
        orig.op("~")(r"(^|-)(" + "|".join(_NON_DEVELOPABLE_LANDUSE_CDS) + r")$"),
        use_txt.like("%RIGHT OF WAY%"),
        use_txt.like("%RIGHT-OF-WAY%"),
        use_txt.like("%EASEMENT%"),
        use_txt.like("%TIDELAND%"),
        use_txt.like("%WATER BODY%"),
        use_txt.like("%OPEN SPACE%"),
        use_txt.like("%FOREST LAND%"),
    )
    vacant = and_(
        ~existing_parking,
        ~non_developable,
        or_(
            and_(bldg.isnot(None), bldg <= 0, land.isnot(None), land > 0),
            use_txt.like("%VACANT%"),
        ),
    )
    underutil = and_(
        ~existing_parking,
        bldg.isnot(None),
        bldg > 0,
        land.isnot(None),
        land > 0,
        (bldg / (bldg + land)) <= UNDERUTILIZED_MAX_IMPROVEMENT_RATIO,
    )
    if s == "existing_parking":
        return existing_parking
    if s == "not_existing_parking":
        return ~existing_parking
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
    situs_address_approximate: bool = False


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
    """Best property/situs line for list views — never treat ZIP-only as an address."""
    from parking_ingestion.address_normalize import looks_like_street

    props = raw_properties or {}
    for key in (
        "PROPERTY_ADDRESS",
        "property_address",
        "VISIT_ADDRESS",
        "visit_address",
        "MAP_ADDRESS",
        "map_address",
        "SITUS_ADDRESS",
        "situs_address",
        "SITUS_ADDR",
        "situs_addr",
        "ADDR_FULL",
        "addr_full",
        "FULLADDR",
        "fulladdr",
        "SITUS_LINE1",
        "situs_line1",
        "LOC_STREET",
    ):
        value = _clean_text(props.get(key))
        if value and looks_like_street(value):
            return value

    line1 = _clean_text(props.get("SITUS_LINE1") or props.get("situs_line1") or props.get("LOC_STREET"))
    city = _clean_text(
        props.get("SITUS_CITY") or props.get("situs_city") or props.get("SITUS_CITY_NM")
    )
    if line1 and looks_like_street(line1):
        return f"{line1}, {city}" if city else line1

    brief_val = _first_brief_contact(brief, "situs_address")
    if brief_val and looks_like_street(brief_val):
        return brief_val
    return None


_HOUSE_NUMBER_PREFIX = re.compile(r"^\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?\s+")


def _street_line_for_house_check(address: str) -> str:
    """Use the street portion before city/state when the value is a full line."""
    text = address.strip()
    if "," in text:
        return text.split(",", 1)[0].strip()
    return text


def situs_address_approximate(
    raw_properties: dict[str, Any] | None,
    *,
    situs_address: str | None = None,
) -> bool:
    """True when the shown situs is a nearby-street fallback (no house number).

    Centroid Nominatim fills often return only a road name (e.g. ``Ramsay Way``) when the
    assessor site address is blank — common for vacant commercial lots.
    """
    props = raw_properties or {}
    flag = props.get("SITUS_ADDRESS_APPROXIMATE")
    if flag is True or str(flag).strip().lower() in {"1", "true", "yes", "y"}:
        return True
    source = str(props.get("ADDRESS_BACKFILL_SOURCE") or "").strip().lower()
    if "nominatim" not in source and "centroid" not in source:
        return False
    line = situs_address or _situs_address(props, None)
    if not line:
        return False
    street = _street_line_for_house_check(line)
    return not bool(_HOUSE_NUMBER_PREFIX.match(street))


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


def _sort_driver_profile(sort: str) -> str:
    """Profile whose ``total_score`` index we walk for top-N candidate selection."""
    if sort == STRATEGIC:
        return STRATEGIC
    if sort == IDENTIFICATION:
        return IDENTIFICATION
    return ENTITLEMENT


def _geography_prefix(county_fips: str, state_fips: str) -> tuple[str | None, str | None]:
    """Return (exact_county, state_prefix) for SQL filters."""
    cf = (county_fips or "").strip()
    st = (state_fips or "").strip()
    if cf:
        return cf, None
    if st:
        return None, f"{st}%"
    return None, None


def _vacant_sql_predicate(alias: str = "p") -> str:
    """Raw SQL fragment: assessor-vacant and not parking / ROW / park / utility."""
    cds = ", ".join(f"'{c}'" for c in _NON_DEVELOPABLE_LANDUSE_CDS)
    return f"""
      NOT (
        NULLIF(BTRIM({alias}.raw_properties->>'LANDUSE_CD'), '') = '46'
        OR NULLIF(BTRIM({alias}.raw_properties->>'LANDUSE_CD'), '') IN ('159', '180', '182')
        OR COALESCE({alias}.raw_properties->>'ORIG_LANDUSE_CD', '') ~ '(^|-)(159|180|182)$'
        OR UPPER(COALESCE({alias}.raw_properties->>'LANDUSE_CD', '')) LIKE '%AUTOMOBILE PARKING%'
        OR UPPER(COALESCE({alias}.raw_properties->>'LANDUSE_CD', '')) LIKE '%PARKING LOT%'
        OR UPPER(COALESCE({alias}.raw_properties->>'LANDUSE_CD', '')) LIKE '%COMMERCIAL PARKING%'
        OR UPPER(COALESCE({alias}.raw_properties->>'LANDUSE_CD', '')) LIKE '%PARKING GARAGE%'
      )
      AND NOT (
        NULLIF(BTRIM({alias}.raw_properties->>'LANDUSE_CD'), '') IN ({cds})
        OR COALESCE({alias}.raw_properties->>'ORIG_LANDUSE_CD', '')
             ~ '(^|-)({"|".join(_NON_DEVELOPABLE_LANDUSE_CDS)})$'
        OR UPPER(COALESCE({alias}.raw_properties->>'LANDUSE_CD', '')) LIKE '%RIGHT OF WAY%'
        OR UPPER(COALESCE({alias}.raw_properties->>'LANDUSE_CD', '')) LIKE '%RIGHT-OF-WAY%'
        OR UPPER(COALESCE({alias}.raw_properties->>'LANDUSE_CD', '')) LIKE '%EASEMENT%'
        OR UPPER(COALESCE({alias}.raw_properties->>'LANDUSE_CD', '')) LIKE '%TIDELAND%'
        OR UPPER(COALESCE({alias}.raw_properties->>'LANDUSE_CD', '')) LIKE '%WATER BODY%'
        OR UPPER(COALESCE({alias}.raw_properties->>'LANDUSE_CD', '')) LIKE '%OPEN SPACE%'
        OR UPPER(COALESCE({alias}.raw_properties->>'LANDUSE_CD', '')) LIKE '%FOREST LAND%'
      )
      AND (
        (
          NULLIF(REPLACE({alias}.raw_properties->>'VALUE_BLDG', ',', ''), '') ~ '^[0-9]+(\\.[0-9]+)?$'
          AND NULLIF(REPLACE({alias}.raw_properties->>'VALUE_BLDG', ',', ''), '')::float <= 0
          AND NULLIF(REPLACE({alias}.raw_properties->>'VALUE_LAND', ',', ''), '') ~ '^[0-9]+(\\.[0-9]+)?$'
          AND NULLIF(REPLACE({alias}.raw_properties->>'VALUE_LAND', ',', ''), '')::float > 0
        )
        OR UPPER(COALESCE({alias}.raw_properties->>'LANDUSE_CD', '')) LIKE '%VACANT%'
      )
    """


def _top_parcel_ids_by_score(
    db: Session,
    *,
    profile: str,
    limit: int,
    county_fips: str,
    state_fips: str,
    overfetch: int | None = None,
    suitability: str | None = None,
) -> list[uuid.UUID]:
    """Walk ``ix_parcel_scores_profile_total_score`` and keep parcels in geography.

    Avoids pivoting every score row in the state (which timed out at 90s+ for WA).
    When ``suitability='vacant'``, filters in SQL so the top page is bare lots
    (not improved buildings that happen to score high).
    """
    cap = min(max(limit, 1), 2000)
    fetch_n = min(max(overfetch or cap, cap), 5000)
    exact, prefix = _geography_prefix(county_fips, state_fips)
    suit = (suitability or "").strip().lower()
    vacant_clause = ""
    if suit == "vacant":
        vacant_clause = f" AND ({_vacant_sql_predicate('p')})"
    if exact:
        sql = text(
            f"""
            SELECT ps.parcel_id
            FROM parcel_scores ps
            JOIN parcels p ON p.id = ps.parcel_id
            WHERE ps.score_profile = :profile
              AND p.county_fips = :exact_county
              {vacant_clause}
            ORDER BY ps.total_score DESC NULLS LAST, ps.created_at DESC
            LIMIT :lim
            """
        )
        params: dict[str, Any] = {"profile": profile, "exact_county": exact, "lim": fetch_n}
    elif prefix:
        sql = text(
            f"""
            SELECT ps.parcel_id
            FROM parcel_scores ps
            JOIN parcels p ON p.id = ps.parcel_id
            WHERE ps.score_profile = :profile
              AND p.county_fips LIKE :state_prefix
              {vacant_clause}
            ORDER BY ps.total_score DESC NULLS LAST, ps.created_at DESC
            LIMIT :lim
            """
        )
        params = {"profile": profile, "state_prefix": prefix, "lim": fetch_n}
    else:
        sql = text(
            """
            SELECT ps.parcel_id
            FROM parcel_scores ps
            WHERE ps.score_profile = :profile
            ORDER BY ps.total_score DESC NULLS LAST, ps.created_at DESC
            LIMIT :lim
            """
        )
        params = {"profile": profile, "lim": fetch_n}
    rows = db.execute(sql, params).all()
    seen: set[uuid.UUID] = set()
    out: list[uuid.UUID] = []
    for (pid,) in rows:
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
        if len(out) >= cap:
            break
    return out


def _hydrate_scored_rows(
    db: Session,
    parcel_ids: list[uuid.UUID],
    *,
    sort: str,
) -> list[ParcelScoredRowData]:
    """Load parcel columns + latest three profile scores for a small id list."""
    if not parcel_ids:
        return []
    has_owner_brief_col = _parcel_column_exists(db, "owner_outreach_brief")
    brief_col = (
        Parcel.owner_outreach_brief
        if has_owner_brief_col
        else literal(None).label("owner_outreach_brief")
    )
    # Latest score per profile for these parcels only.
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
        .where(ParcelScore.parcel_id.in_(parcel_ids))
        .where(ParcelScore.score_profile.in_((ENTITLEMENT, STRATEGIC, IDENTIFICATION)))
        .subquery()
    )
    pivot = (
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
    stmt = (
        select(
            Parcel.id,
            Parcel.apn,
            Parcel.county_fips,
            Parcel.zoning_code,
            Parcel.raw_properties,
            brief_col,
            Parcel.lot_sqft,
            Parcel.created_at,
            pivot.c.ent_score,
            pivot.c.str_score,
            pivot.c.id_score,
        )
        .outerjoin(pivot, Parcel.id == pivot.c.parcel_id)
        .where(Parcel.id.in_(parcel_ids))
    )
    by_id: dict[uuid.UUID, ParcelScoredRowData] = {}
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
        situs = _situs_address(raw_dict, brief_dict)
        by_id[pid] = ParcelScoredRowData(
            parcel_id=pid,
            apn=apn,
            county_fips=cfips,
            situs_address=situs,
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
            situs_address_approximate=situs_address_approximate(raw_dict, situs_address=situs),
        )

    def sort_key(row: ParcelScoredRowData) -> tuple[float, float]:
        if sort == ENTITLEMENT:
            primary = row.entitlement_score
        elif sort == STRATEGIC:
            primary = row.strategic_score
        elif sort == IDENTIFICATION:
            primary = row.identification_score
        else:
            primary = row.combined_score
        return (
            primary if primary is not None else float("-inf"),
            row.created_at.timestamp() if row.created_at else 0.0,
        )

    ordered = [by_id[pid] for pid in parcel_ids if pid in by_id]
    ordered.sort(key=sort_key, reverse=True)
    return ordered


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
    """Parcels with latest scores, ordered by ``sort`` (null scores last).

    When a state/county is set (normal operator-console path), uses an index walk on
    ``parcel_scores (score_profile, total_score)`` so statewide lists finish in seconds
    instead of scanning every WA score row.
    """
    cap = min(max(limit, 1), 2000)
    cf = (county_fips or "").strip()
    st = (state_fips or "").strip()
    tier = (zoning_tier or "").strip().lower()
    suit = (suitability or "").strip().lower()

    # Fast path: geography selected, suitability/tier applied after hydrate.
    # Keep overfetch modest — large LIMIT+JOIN walks on parcel_scores time out for WA.
    # Vacant is applied in the score walk SQL so we do not overfetch improved buildings.
    if cf or st:
        if suit == "vacant":
            overfetch = min(cap * 4, 200)
        elif suit in ("not_existing_parking", "existing_parking"):
            # Parking-coded lots are sparse among top scores.
            overfetch = min(cap * 8, 400)
        elif suit or tier or min_entitlement_score is not None:
            overfetch = min(cap * 20, 800)
        else:
            overfetch = min(cap * 4, 200)
        driver = _sort_driver_profile(sort)
        ids = _top_parcel_ids_by_score(
            db,
            profile=driver,
            limit=overfetch,
            county_fips=cf,
            state_fips=st,
            overfetch=overfetch,
            suitability=suit if suit == "vacant" else None,
        )
        rows = _hydrate_scored_rows(db, ids, sort=sort)
        if tier in ("prospect", "prospects"):
            rows = [
                r
                for r in rows
                if (r.zoning_entitlement_tier or "") in ("permitted", "conditional", "provisional")
            ]
        elif tier:
            rows = [r for r in rows if (r.zoning_entitlement_tier or "") == tier]
        if suit in (
            "vacant",
            "underutilized",
            "vacant_or_underutilized",
            "existing_parking",
            "not_existing_parking",
        ):
            if suit == "vacant":
                rows = [r for r in rows if r.suitability == "vacant"]
            elif suit == "underutilized":
                rows = [r for r in rows if r.suitability == "underutilized"]
            elif suit == "vacant_or_underutilized":
                rows = [r for r in rows if r.suitability in ("vacant", "underutilized")]
            elif suit == "existing_parking":
                rows = [r for r in rows if r.suitability == "existing_parking"]
            else:
                rows = [r for r in rows if r.suitability != "existing_parking"]
        if min_entitlement_score is not None:
            floor = float(min_entitlement_score)
            rows = [r for r in rows if r.entitlement_score is not None and r.entitlement_score >= floor]
        return rows[:cap]

    # Legacy full-scan path (no geography) — kept for API callers; UI requires a state.
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
        suit_info = compute_parcel_suitability(raw_dict)
        situs = _situs_address(raw_dict, brief_dict)
        out.append(
            ParcelScoredRowData(
                parcel_id=pid,
                apn=apn,
                county_fips=cfips,
                situs_address=situs,
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
                suitability=suit_info["suitability"],
                is_vacant_land=suit_info["is_vacant_land"],
                improvement_ratio=suit_info["improvement_ratio"],
                situs_address_approximate=situs_address_approximate(raw_dict, situs_address=situs),
            ),
        )
    return out
