"""Jurisdiction-level data quality and parity analytics.

This report complements global export-readiness counts by grouping parcels by
county plus the best available zoning jurisdiction label. It is intentionally
read-only and can be run hours or days after ingest to find stale data gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import literal, select
from sqlalchemy.orm import Session

from app.db.models import Parcel
from app.db.schema_compat import column_exists
from app.pipeline_funnel import entitlement_qualified_floor
from app.scoring_profiles import ENTITLEMENT, IDENTIFICATION, STRATEGIC
from app.scoring_summary import _latest_scores_subquery

QUALITY_FIELDS = (
    "footprint",
    "zoning",
    "lot_size",
    "demand_distance",
    "poi_density",
    "owner_roll_name",
    "owner_outreach_brief",
    "identification_score",
    "entitlement_score",
    "strategic_score",
)

OWNER_KEYS = (
    "OWNER_NAME",
    "OWNER",
    "owner_name",
    "owner",
    "TAXPAYER_NAME",
    "TaxpayerName",
    "MAIL_NAME",
)

JURISDICTION_KEYS = (
    "ZONING_JURISDICTION",
    "zoning_jurisdiction",
    "JURISDICTION",
    "jurisdiction",
    "CITY",
    "city",
    "SITUS_CITY",
    "SITE_CITY",
)


@dataclass(frozen=True)
class ParcelQualityRecord:
    county_fips: str
    zoning_jurisdiction: str | None
    has_footprint: bool
    has_zoning: bool
    has_lot_size: bool
    has_demand_distance: bool
    has_poi_density: bool
    has_owner_roll_name: bool
    has_owner_outreach_brief: bool
    has_identification_score: bool
    has_entitlement_score: bool
    has_strategic_score: bool
    entitlement_score: float | None
    created_at: datetime | None


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * float(part) / float(total), 2)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _clean_label(raw: Any) -> str | None:
    if raw is None:
        return None
    label = str(raw).strip()
    if not label:
        return None
    lowered = label.lower()
    if lowered in {"none", "null", "nan", "unknown", "n/a"}:
        return None
    return label


def _extract_first(raw: dict[str, Any] | None, keys: tuple[str, ...]) -> str | None:
    if not isinstance(raw, dict):
        return None
    for key in keys:
        label = _clean_label(raw.get(key))
        if label:
            return label
    return None


def _jurisdiction_key(county_fips: str, zoning_jurisdiction: str | None) -> str:
    if zoning_jurisdiction:
        return f"{county_fips}:{zoning_jurisdiction}"
    return f"{county_fips}:county_unknown"


def _jurisdiction_label(county_fips: str, zoning_jurisdiction: str | None) -> str:
    if zoning_jurisdiction:
        return f"{zoning_jurisdiction} ({county_fips})"
    return f"County {county_fips} / jurisdiction unknown"


def _quality_metric(missing: int, total: int) -> dict[str, Any]:
    return {"count": missing, "pct": _pct(missing, total)}


def _coverage_score(group: dict[str, Any]) -> float:
    total = int(group["parcel_count"])
    if total <= 0:
        return 0.0
    present = 0
    present += total - group["missing_footprint"]
    present += total - group["missing_zoning"]
    present += total - group["missing_lot_size"]
    present += total - group["missing_demand_distance"]
    present += total - group["missing_poi_density"]
    present += total - group["missing_owner_roll_name"]
    present += total - group["missing_owner_outreach_brief"]
    present += total - group["missing_identification_score"]
    present += total - group["missing_entitlement_score"]
    present += total - group["missing_strategic_score"]
    return round(100.0 * present / float(total * len(QUALITY_FIELDS)), 2)


def _recommended_actions(group: dict[str, Any]) -> list[str]:
    total = int(group["parcel_count"])
    if total <= 0:
        return []

    actions: list[str] = []

    def gap(field: str) -> float:
        return _pct(int(group[field]), total)

    if gap("missing_zoning") >= 10:
        actions.append("Build or merge the zoning overlay and jurisdiction-specific parking rules.")
    if int(group["unresolved_core_gaps_older_24h"]) > 0:
        actions.append("Inspect rows still missing core fields after 24h; they likely need source or pipeline repair.")
    if gap("missing_entitlement_score") >= 10 or gap("missing_strategic_score") >= 10:
        actions.append("Drain the full scoring pipeline for prescreen-qualified parcels.")
    if gap("missing_demand_distance") >= 10:
        actions.append("Refresh demand distances after seeding real demand generators for this market.")
    if gap("missing_poi_density") >= 10:
        actions.append("Run POI density refresh so revenue/demand confidence is comparable.")
    if gap("missing_owner_roll_name") >= 10:
        actions.append("Fix assessor roll owner-name mapping before outreach enrichment.")
    if gap("missing_owner_outreach_brief") >= 10 and int(group["qualified_entitlement_count"]) > 0:
        actions.append("Run owner/outreach enrichment for entitlement-qualified parcels.")

    if not actions and int(group["qualified_entitlement_count"]) > 0:
        actions.append("Use this jurisdiction as a benchmark playbook for weaker markets.")
    elif not actions:
        actions.append("Coverage is healthy; next step is opportunity review and manual spot checks.")

    return actions[:5]


def _empty_group(key: str, county_fips: str, zoning_jurisdiction: str | None) -> dict[str, Any]:
    return {
        "jurisdiction_key": key,
        "label": _jurisdiction_label(county_fips, zoning_jurisdiction),
        "county_fips": county_fips,
        "zoning_jurisdiction": zoning_jurisdiction,
        "parcel_count": 0,
        "qualified_entitlement_count": 0,
        "parcels_arrived_last_24h": 0,
        "parcels_arrived_1_to_7d": 0,
        "parcels_arrived_older_7d": 0,
        "unresolved_core_gaps_older_24h": 0,
        "unresolved_core_gaps_older_7d": 0,
        "missing_footprint": 0,
        "missing_zoning": 0,
        "missing_lot_size": 0,
        "missing_demand_distance": 0,
        "missing_poi_density": 0,
        "missing_owner_roll_name": 0,
        "missing_owner_outreach_brief": 0,
        "missing_identification_score": 0,
        "missing_entitlement_score": 0,
        "missing_strategic_score": 0,
    }


def _has_core_gap(record: ParcelQualityRecord) -> bool:
    return not (
        record.has_footprint
        and record.has_zoning
        and record.has_lot_size
        and record.has_identification_score
        and record.has_entitlement_score
    )


def _summarize_records(
    records: list[ParcelQualityRecord],
    *,
    now: datetime,
    entitlement_floor: float,
    limit: int = 25,
) -> dict[str, Any]:
    now = _as_aware(now) or datetime.now(tz=UTC)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    groups: dict[str, dict[str, Any]] = {}
    for record in records:
        key = _jurisdiction_key(record.county_fips, record.zoning_jurisdiction)
        group = groups.setdefault(key, _empty_group(key, record.county_fips, record.zoning_jurisdiction))
        group["parcel_count"] += 1

        if record.entitlement_score is not None and float(record.entitlement_score) >= entitlement_floor:
            group["qualified_entitlement_count"] += 1

        created = _as_aware(record.created_at)
        if created is not None:
            if created >= cutoff_24h:
                group["parcels_arrived_last_24h"] += 1
            elif created >= cutoff_7d:
                group["parcels_arrived_1_to_7d"] += 1
            else:
                group["parcels_arrived_older_7d"] += 1

            if _has_core_gap(record):
                if created < cutoff_24h:
                    group["unresolved_core_gaps_older_24h"] += 1
                if created < cutoff_7d:
                    group["unresolved_core_gaps_older_7d"] += 1

        if not record.has_footprint:
            group["missing_footprint"] += 1
        if not record.has_zoning:
            group["missing_zoning"] += 1
        if not record.has_lot_size:
            group["missing_lot_size"] += 1
        if not record.has_demand_distance:
            group["missing_demand_distance"] += 1
        if not record.has_poi_density:
            group["missing_poi_density"] += 1
        if not record.has_owner_roll_name:
            group["missing_owner_roll_name"] += 1
        if not record.has_owner_outreach_brief:
            group["missing_owner_outreach_brief"] += 1
        if not record.has_identification_score:
            group["missing_identification_score"] += 1
        if not record.has_entitlement_score:
            group["missing_entitlement_score"] += 1
        if not record.has_strategic_score:
            group["missing_strategic_score"] += 1

    benchmark = 0.0
    for group in groups.values():
        group["quality_score"] = _coverage_score(group)
        benchmark = max(benchmark, float(group["quality_score"]))

    rows: list[dict[str, Any]] = []
    for group in groups.values():
        total = int(group["parcel_count"])
        parity_gap = round(max(0.0, benchmark - float(group["quality_score"])), 2)
        qualified_pct = _pct(int(group["qualified_entitlement_count"]), total)
        stale_pct = _pct(int(group["unresolved_core_gaps_older_24h"]), total)
        scale_bonus = min(20.0, total / 1000.0)
        opportunity = round(min(100.0, parity_gap * 0.55 + qualified_pct * 0.25 + stale_pct * 0.15 + scale_bonus), 2)
        rows.append(
            {
                "jurisdiction_key": group["jurisdiction_key"],
                "label": group["label"],
                "county_fips": group["county_fips"],
                "zoning_jurisdiction": group["zoning_jurisdiction"],
                "parcel_count": total,
                "quality_score": group["quality_score"],
                "parity_gap_to_best": parity_gap,
                "opportunity_score": opportunity,
                "qualified_entitlement_count": int(group["qualified_entitlement_count"]),
                "qualified_entitlement_pct": qualified_pct,
                "age_buckets": {
                    "last_24h": int(group["parcels_arrived_last_24h"]),
                    "days_1_to_7": int(group["parcels_arrived_1_to_7d"]),
                    "older_7d": int(group["parcels_arrived_older_7d"]),
                },
                "unresolved_core_gaps_older_24h": int(group["unresolved_core_gaps_older_24h"]),
                "unresolved_core_gaps_older_7d": int(group["unresolved_core_gaps_older_7d"]),
                "missing_footprint": _quality_metric(int(group["missing_footprint"]), total),
                "missing_zoning": _quality_metric(int(group["missing_zoning"]), total),
                "missing_lot_size": _quality_metric(int(group["missing_lot_size"]), total),
                "missing_demand_distance": _quality_metric(int(group["missing_demand_distance"]), total),
                "missing_poi_density": _quality_metric(int(group["missing_poi_density"]), total),
                "missing_owner_roll_name": _quality_metric(int(group["missing_owner_roll_name"]), total),
                "missing_owner_outreach_brief": _quality_metric(int(group["missing_owner_outreach_brief"]), total),
                "missing_identification_score": _quality_metric(int(group["missing_identification_score"]), total),
                "missing_entitlement_score": _quality_metric(int(group["missing_entitlement_score"]), total),
                "missing_strategic_score": _quality_metric(int(group["missing_strategic_score"]), total),
                "recommended_actions": _recommended_actions(group),
            },
        )

    rows.sort(key=lambda row: (float(row["opportunity_score"]), int(row["parcel_count"])), reverse=True)
    top_actions: list[str] = []
    for row in rows[:5]:
        actions = row.get("recommended_actions") or []
        if actions:
            top_actions.append(f"{row['label']}: {actions[0]}")

    return {
        "generated_at": now,
        "total_parcels": len(records),
        "jurisdiction_count": len(rows),
        "benchmark_quality_score": round(benchmark, 2),
        "watch_windows_hours": [24, 168],
        "rows": rows[: max(1, limit)],
        "top_actions": top_actions,
        "notes": [
            "Rows are grouped by county FIPS plus raw_properties ZONING_JURISDICTION when available.",
            "The 24h/7d stale-gap counters use parcels.created_at; updated existing APNs are tracked by "
            "ingest audit events until parcels get an updated_at column.",
        ],
    }


def _records_from_db(db: Session) -> list[ParcelQualityRecord]:
    ident = _latest_scores_subquery(IDENTIFICATION)
    ent = _latest_scores_subquery(ENTITLEMENT)
    strat = _latest_scores_subquery(STRATEGIC)
    poi_col = (
        Parcel.poi_commercial_count_400m
        if column_exists(db, "parcels", "poi_commercial_count_400m")
        else literal(None)
    )
    stmt = (
        select(
            Parcel.county_fips.label("county_fips"),
            Parcel.raw_properties.label("raw_properties"),
            Parcel.footprint.isnot(None).label("has_footprint"),
            Parcel.zoning_code.label("zoning_code"),
            Parcel.lot_sqft.label("lot_sqft"),
            Parcel.distance_to_nearest_demand_m.label("distance_to_nearest_demand_m"),
            poi_col.label("poi_commercial_count_400m"),
            Parcel.owner_outreach_brief.label("owner_outreach_brief"),
            Parcel.created_at.label("created_at"),
            ident.c.total_score.label("identification_score"),
            ent.c.total_score.label("entitlement_score"),
            strat.c.total_score.label("strategic_score"),
        )
        .select_from(Parcel)
        .outerjoin(ident, ident.c.parcel_id == Parcel.id)
        .outerjoin(ent, ent.c.parcel_id == Parcel.id)
        .outerjoin(strat, strat.c.parcel_id == Parcel.id)
    )

    records: list[ParcelQualityRecord] = []
    for row in db.execute(stmt):
        m = row._mapping
        raw = m["raw_properties"] if isinstance(m["raw_properties"], dict) else None
        records.append(
            ParcelQualityRecord(
                county_fips=str(m["county_fips"]),
                zoning_jurisdiction=_extract_first(raw, JURISDICTION_KEYS),
                has_footprint=bool(m["has_footprint"]),
                has_zoning=_clean_label(m["zoning_code"]) is not None,
                has_lot_size=m["lot_sqft"] is not None,
                has_demand_distance=m["distance_to_nearest_demand_m"] is not None,
                has_poi_density=m["poi_commercial_count_400m"] is not None,
                has_owner_roll_name=_extract_first(raw, OWNER_KEYS) is not None,
                has_owner_outreach_brief=isinstance(m["owner_outreach_brief"], dict),
                has_identification_score=m["identification_score"] is not None,
                has_entitlement_score=m["entitlement_score"] is not None,
                has_strategic_score=m["strategic_score"] is not None,
                entitlement_score=float(m["entitlement_score"]) if m["entitlement_score"] is not None else None,
                created_at=m["created_at"],
            ),
        )
    return records


def jurisdiction_quality_summary(db: Session, *, limit: int = 25) -> dict[str, Any]:
    """Return jurisdiction-level data quality, stale-gap, and parity recommendations."""
    limit = min(max(1, int(limit)), 100)
    records = _records_from_db(db)
    return _summarize_records(
        records,
        now=datetime.now(tz=UTC),
        entitlement_floor=entitlement_qualified_floor(),
        limit=limit,
    )
