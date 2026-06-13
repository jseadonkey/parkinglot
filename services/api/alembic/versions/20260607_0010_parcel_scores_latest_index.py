"""Add latest-score lookup index for parcel score lists.

Revision ID: 20260607_0010
Revises: 0011
Create Date: 2026-06-07
"""

from __future__ import annotations

from alembic import op

from app.db.migration_util import index_exists


revision = "20260607_0010"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not index_exists("parcel_scores", "ix_parcel_scores_parcel_profile_created_at"):
        op.create_index(
            "ix_parcel_scores_parcel_profile_created_at",
            "parcel_scores",
            ["parcel_id", "score_profile", "created_at"],
        )


def downgrade() -> None:
    if index_exists("parcel_scores", "ix_parcel_scores_parcel_profile_created_at"):
        op.drop_index("ix_parcel_scores_parcel_profile_created_at", table_name="parcel_scores")
