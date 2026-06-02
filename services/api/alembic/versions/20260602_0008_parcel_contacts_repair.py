"""Ensure parcel_contact_points + outreach_attempts exist (repair skipped 0004).

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-02

Production may have alembic_version at 0007 while migration 0004 was skipped on a
legacy branch stamp — recreate missing tables idempotently.
"""

from typing import Union
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.migration_util import table_exists

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("parcel_contact_points"):
        op.create_table(
            "parcel_contact_points",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("parcel_id", UUID(as_uuid=True), sa.ForeignKey("parcels.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("normalized_value", sa.Text(), nullable=False),
            sa.Column("source", sa.String(length=128), nullable=False, server_default=sa.text("'assessor_roll'")),
            sa.Column("label", sa.String(length=256), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0.5")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )
        op.create_index(
            "ix_parcel_contact_points_parcel_kind_norm",
            "parcel_contact_points",
            ["parcel_id", "kind", "normalized_value"],
            unique=True,
        )

    if not table_exists("outreach_attempts"):
        op.create_table(
            "outreach_attempts",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("parcel_id", UUID(as_uuid=True), sa.ForeignKey("parcels.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "contact_point_id",
                UUID(as_uuid=True),
                sa.ForeignKey("parcel_contact_points.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("target_kind", sa.String(length=32), nullable=False),
            sa.Column("target_value", sa.Text(), nullable=False),
            sa.Column("result", sa.String(length=64), nullable=False, server_default=sa.text("'attempted'")),
            sa.Column("result_detail", sa.Text(), nullable=True),
            sa.Column("attempted_by", sa.String(length=256), nullable=False),
            sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column(
                "approval_request_id",
                UUID(as_uuid=True),
                sa.ForeignKey("approval_requests.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("meta", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )
        op.create_index("ix_outreach_attempts_parcel_attempted_at", "outreach_attempts", ["parcel_id", "attempted_at"])


def downgrade() -> None:
    pass
