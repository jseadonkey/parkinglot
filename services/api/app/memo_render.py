from __future__ import annotations

from parking_core.models import OwnerOutreachBrief, ScoreResult


def build_deal_memo_markdown(
    *,
    apn: str,
    county_fips: str,
    zoning_code: str | None,
    lot_sqft: float | None,
    score: ScoreResult,
    owner_lines: list[str],
    outreach_brief: OwnerOutreachBrief | None = None,
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
        ]
    )
    if outreach_brief is not None:
        ob = outreach_brief
        step_lines = []
        for s in ob.steps:
            step_lines.append(
                f"{s.rank}. **{s.title}** (`{s.channel.value}`) — conf {s.confidence:.2f}, "
                f"human={'yes' if s.requires_human else 'no'}\n   - {s.instruction}"
            )
        gap_lines = "\n".join(f"- {g}" for g in ob.data_gaps) or "- (none)"
        comp_lines = "\n".join(f"- {c}" for c in ob.compliance_notes) or "- (none)"
        contact_bits = [
            f"- **Recorded owner**: {ob.recorded_owner_one_liner}",
        ]
        if ob.mailing_address_guess:
            contact_bits.append(f"- **Mailing (guess)**: {ob.mailing_address_guess}")
        if ob.situs_address_guess:
            contact_bits.append(f"- **Situs (guess)**: {ob.situs_address_guess}")
        if ob.phone_guess:
            contact_bits.append(f"- **Phone (guess)**: {ob.phone_guess}")
        if ob.email_guess:
            contact_bits.append(f"- **Email (guess)**: {ob.email_guess}")
        extra = "\n".join(
            [
                "",
                "## Owner outreach brief (deterministic rules)",
                "\n".join(contact_bits),
                "",
                "### Prioritized steps",
                "\n".join(step_lines) if step_lines else "- (none)",
                "",
                "### Data gaps",
                gap_lines,
                "",
                "### Compliance",
                comp_lines,
                "",
            ]
        )
        md = md + extra
    md += "\n".join(
        [
            "## Non-binding next steps",
            "- Human review of this memo and attached draft contract.",
            "- Counsel review before any outreach or execution.",
        ]
    )
    return title, md, open_questions