from __future__ import annotations

from parking_core.models import ScoreResult


def build_deal_memo_markdown(
    *,
    apn: str,
    county_fips: str,
    zoning_code: str | None,
    lot_sqft: float | None,
    score: ScoreResult,
    owner_lines: list[str],
) -> tuple[str, str, list[str]]:
    title = f"Deal memo — {apn} ({county_fips})"
    open_questions = [
        "Confirm zoning allows surface parking operation (not only ingest flag).",
        "Validate owner / decision-maker via SOS or direct outreach.",
        "Competitive set and achievable ADR / occupancy assumptions.",
    ]
    md = "\n".join(
        [
            f"# {title}",
            "",
            "## Parcel snapshot",
            f"- **APN**: {apn}",
            f"- **County FIPS**: {county_fips}",
            f"- **Zoning code**: {zoning_code or 'unknown'}",
            f"- **Lot size**: {lot_sqft or 'unknown'} sqft",
            "",
            "## Suitability score (deterministic)",
            f"- **Total**: {score.total_score:.1f} / 100",
            f"- **Zoning component**: {score.breakdown.zoning_component}",
            f"- **Lot size component**: {score.breakdown.lot_size_component}",
            f"- **Corner component**: {score.breakdown.corner_component}",
            f"- **Demand proximity component**: {score.breakdown.demand_proximity_component}",
            "",
            "### Notes",
            "\n".join(f"- {n}" for n in score.breakdown.notes) or "- (none)",
            "",
            "## Owner candidates (enrichment)",
            "\n".join(f"- {line}" for line in owner_lines) or "- (none)",
            "",
            "## Non-binding next steps",
            "- Human review of this memo and attached draft contract.",
            "- Counsel review before any outreach or execution.",
        ]
    )
    return title, md, open_questions