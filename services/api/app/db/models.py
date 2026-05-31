from __future__ import annotations

import uuid
from datetime import datetime

import geoalchemy2
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Parcel(Base):
    __tablename__ = "parcels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    apn: Mapped[str] = mapped_column(String(128), nullable=False)
    county_fips: Mapped[str] = mapped_column(String(5), nullable=False)
    lot_sqft: Mapped[float | None] = mapped_column(Float, nullable=True)
    zoning_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    zoning_allows_surface_parking: Mapped[bool] = mapped_column(default=False)
    is_corner_lot: Mapped[bool] = mapped_column(default=False)
    distance_to_nearest_demand_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_to_nearest_comp_parking_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    nearest_parking_comp: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pilot_in_scope: Mapped[bool] = mapped_column(default=True, nullable=False)
    raw_properties: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    owner_outreach_brief: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    footprint: Mapped[object | None] = mapped_column(
        geoalchemy2.Geometry(geometry_type="MULTIPOLYGON", srid=4326),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scores: Mapped[list[ParcelScore]] = relationship(back_populates="parcel")
    owners: Mapped[list[OwnerCandidateRow]] = relationship(back_populates="parcel")
    memos: Mapped[list[DealMemo]] = relationship(back_populates="parcel")


class ParcelScore(Base):
    __tablename__ = "parcel_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parcel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parcels.id", ondelete="CASCADE"))
    # entitlement = zoning-forward (pilot.yaml); strategic = demand/visibility-forward (pilot_strategic.yaml)
    score_profile: Mapped[str] = mapped_column(String(32), nullable=False, default="entitlement")
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pilot_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parcel: Mapped[Parcel] = relationship(back_populates="scores")


class OwnerCandidateRow(Base):
    __tablename__ = "owner_candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parcel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parcels.id", ondelete="CASCADE"))
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    normalized_owner_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parcel: Mapped[Parcel] = relationship(back_populates="owners")


class DealMemo(Base):
    __tablename__ = "deal_memos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parcel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parcels.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    open_questions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parcel: Mapped[Parcel] = relationship(back_populates="memos")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parcel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parcels.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractDraft(Base):
    __tablename__ = "contract_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parcel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parcels.id", ondelete="CASCADE"))
    s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor: Mapped[str] = mapped_column(String(256), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
