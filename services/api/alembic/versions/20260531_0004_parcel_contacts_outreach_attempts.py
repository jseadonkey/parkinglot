"""parcel contact points + outreach attempts

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-31

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
    op.drop_index("ix_outreach_attempts_parcel_attempted_at", table_name="outreach_attempts")
    op.drop_table("outreach_attempts")
    op.drop_index("ix_parcel_contact_points_parcel_kind_norm", table_name="parcel_contact_points")
    op.drop_table("parcel_contact_points")
