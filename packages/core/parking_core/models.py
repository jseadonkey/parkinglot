from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ParcelFeature(BaseModel):
    """Normalized parcel attributes used by scoring (deterministic inputs)."""

    apn: str
    county_fips: str
    lot_sqft: float | None = None
    zoning_code: str | None = None
    zoning_allows_surface_parking: bool = False
    is_corner_lot: bool = False
    distance_to_nearest_demand_m: float | None = None
    raw_properties: dict[str, Any] | None = None


class ScoreBreakdown(BaseModel):
    zoning_component: float
    lot_size_component: float
    corner_component: float
    demand_proximity_component: float
    notes: list[str] = Field(default_factory=list)


class ScoreResult(BaseModel):
    total_score: float
    breakdown: ScoreBreakdown
    pilot_snapshot: dict[str, Any] = Field(default_factory=dict)


class OwnerKind(StrEnum):
    individual = "individual"
    entity = "entity"
    unknown = "unknown"


class OwnerCandidate(BaseModel):
    display_name: str
    kind: OwnerKind
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    raw: dict[str, Any] = Field(default_factory=dict)


class ContactKind(StrEnum):
    email = "email"
    phone = "phone"
    mailing_address = "mailing_address"
    situs_address = "situs_address"


class OutreachChannel(StrEnum):
    """How we might reach the owner or their representative."""

    secretary_of_state = "secretary_of_state"
    certified_mail = "certified_mail"
    phone = "phone"
    email = "email"
    site_visit = "site_visit"
    vendor_research = "vendor_research"


class OutreachResult(StrEnum):
    attempted = "attempted"
    sent = "sent"
    delivered = "delivered"
    opened = "opened"
    bounced = "bounced"
    no_answer = "no_answer"
    voicemail = "voicemail"
    wrong_number = "wrong_number"
    disconnected = "disconnected"
    replied_interested = "replied_interested"
    replied_not_interested = "replied_not_interested"
    returned_mail = "returned_mail"
    not_deliverable = "not_deliverable"
    meeting_scheduled = "meeting_scheduled"
    unknown = "unknown"


class OwnerContactPoint(BaseModel):
    kind: ContactKind
    value: str
    source: str = "assessor_roll"
    label: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    id: str | None = None


class OutreachAttemptRead(BaseModel):
    id: str
    parcel_id: str
    contact_point_id: str | None = None
    channel: OutreachChannel
    target_kind: ContactKind
    target_value: str
    result: OutreachResult = OutreachResult.attempted
    result_detail: str | None = None
    attempted_by: str
    attempted_at: datetime
    approval_request_id: str | None = None


class OutreachStep(BaseModel):
    """One prioritized outreach move (human or system may execute)."""

    rank: int = Field(ge=1, description="1 = try first")
    channel: OutreachChannel
    title: str
    instruction: str
    confidence: float = Field(ge=0.0, le=1.0)
    requires_human: bool = False


class RegistryLookupSummary(BaseModel):
    """Result of an automated registry HTTP lookup (e.g. WA SOS name search)."""

    state: str
    provider: str
    query_used: str
    outcome: Literal[
        "hit",
        "no_results",
        "error",
        "skipped_not_wa",
        "skipped_not_entity",
        "manual_url_only",
    ]
    http_status: int | None = None
    raw_result_count: int = 0
    top_match_name: str | None = None
    top_match_ubi: str | None = None
    search_results_url: str | None = None
    detail_url: str | None = None
    error_detail: str | None = None
    registered_agent_line: str | None = None
    principal_address_line: str | None = None
    detail_http_status: int | None = None
    detail_fetch_error: str | None = None
    notes: str | None = Field(default=None, description="Human-readable context (not from registry payload).")


class VendorContactHint(BaseModel):
    channel: str
    value: str
    label: str | None = None


class VendorLookupSummary(BaseModel):
    """Normalized response from an optional outbound vendor webhook."""

    provider: str = "webhook"
    outcome: Literal["hit", "skipped_no_url", "skipped_disabled", "error"]
    http_status: int | None = None
    notes: str | None = None
    contacts: list[VendorContactHint] = Field(default_factory=list)
    error_detail: str | None = None


class OwnerOutreachBrief(BaseModel):
    """
    Agent output: who we think owns the lot (from enrichment) and how to contact them.
    Deterministic v1 rules; swap in vendor / LLM enrichment later without changing the shape.
    """

    schema_version: str = "2"
    county_fips: str
    apn: str
    recorded_owner_one_liner: str
    contact_points: list[OwnerContactPoint] = Field(default_factory=list)
    mailing_address_guess: str | None = None
    situs_address_guess: str | None = None
    phone_guess: str | None = None
    email_guess: str | None = None
    steps: list[OutreachStep] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    compliance_notes: list[str] = Field(default_factory=list)
    registry_lookup: RegistryLookupSummary | None = None
    vendor_lookup: VendorLookupSummary | None = None
    normalized_owner_key: str | None = Field(
        default=None,
        description="US-state-scoped dedupe key for portfolio rollup (see enrichment.normalize).",
    )
    same_owner_qualified_other_count: int | None = Field(
        default=None,
        description=(
            "Other parcels in DB with same normalized_owner_key whose latest entitlement score "
            "meets pilot floor."
        ),
    )
    same_owner_peer_examples: list[str] = Field(
        default_factory=list,
        description='Short labels e.g. "53033 / 1234567890" for peer parcels.',
    )
    manual_research_checklist: list[str] = Field(
        default_factory=list,
        description="Human-only OSINT-style prompts (no automated scraping).",
    )
    computed_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when this brief was last persisted (recompute or pipeline).",
    )


class OutboundMessageChannel(StrEnum):
    email = "email"
    sms = "sms"
    certified_mail = "certified_mail"
    phone = "phone"


class OutreachTemplateSlug(StrEnum):
    certified_mail_letter = "certified_mail_letter"
    phone_call_script = "phone_call_script"
    email_outreach = "email_outreach"
    sms_outreach = "sms_outreach"


OUTREACH_TEMPLATE_PLACEHOLDERS: list[str] = [
    "owner_name",
    "mailing_address",
    "situs_address",
    "apn",
    "county_fips",
    "lot_sqft",
    "region_name",
    "sender_name",
    "sender_company",
    "sender_email",
    "sender_phone",
]


class OutboundMessageDraft(BaseModel):
    """A human-reviewable outreach message draft (no sending)."""

    channel: OutboundMessageChannel
    to_name: str | None = None
    to_email: str | None = None
    to_mailing_address: str | None = None
    from_name: str
    from_company: str | None = None
    from_email: str | None = None
    from_phone: str | None = None
    subject: str | None = None
    body: str
    created_at: datetime | None = None


class DealMemoPayload(BaseModel):
    parcel_id: str
    title: str
    markdown: str
    open_questions: list[str] = Field(default_factory=list)


class ApprovalType(StrEnum):
    outbound_message = "outbound_message"
    contract_send = "contract_send"
    deal_memo_publish = "deal_memo_publish"


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ApprovalRequestRead(BaseModel):
    id: str
    type: ApprovalType
    status: ApprovalStatus
    payload: dict[str, Any]
    created_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None


class AuditLogEntry(BaseModel):
    id: str
    actor: str
    action: str
    entity_type: str
    entity_id: str | None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
