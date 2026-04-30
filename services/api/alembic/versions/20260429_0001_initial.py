"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-29

"""

from typing import Sequence, Union

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "parcels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("apn", sa.String(length=128), nullable=False),
        sa.Column("county_fips", sa.String(length=5), nullable=False),
        sa.Column("lot_sqft", sa.Float(), nullable=True),
        sa.Column("zoning_code", sa.String(length=64), nullable=True),
        sa.Column("zoning_allows_surface_parking", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_corner_lot", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("distance_to_nearest_demand_m", sa.Float(), nullable=True),
        sa.Column("raw_properties", JSONB(), nullable=True),
        sa.Column(
            "footprint",
            geoalchemy2.types.Geometry(geometry_type="MULTIPOLYGON", srid=4326, dimension=2),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_parcels_county_apn", "parcels", ["county_fips", "apn"], unique=False)
    op.execute("CREATE INDEX ix_parcels_footprint ON parcels USING GIST (footprint)")

    op.create_table(
        "parcel_scores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("parcel_id", UUID(as_uuid=True), sa.ForeignKey("parcels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("breakdown", JSONB(), nullable=False),
        sa.Column("pilot_snapshot", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "owner_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("parcel_id", UUID(as_uuid=True), sa.ForeignKey("parcels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("raw", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "deal_memos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("parcel_id", UUID(as_uuid=True), sa.ForeignKey("parcels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("open_questions", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("parcel_id", UUID(as_uuid=True), sa.ForeignKey("parcels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "approval_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("approved_by", sa.String(length=256), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "contract_drafts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("parcel_id", UUID(as_uuid=True), sa.ForeignKey("parcels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("s3_key", sa.String(length=512), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("actor", sa.String(length=256), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=True),
        sa.Column("meta", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("contract_drafts")
    op.drop_table("approval_requests")
    op.drop_table("workflow_runs")
    op.drop_table("deal_memos")
    op.drop_table("owner_candidates")
    op.drop_table("parcel_scores")
    op.execute("DROP INDEX IF EXISTS ix_parcels_footprint")
    op.drop_table("parcels")
