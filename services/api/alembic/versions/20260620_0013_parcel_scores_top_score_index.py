"""Add top-score index for operator scored parcel lists.

Revision ID: 20260620_0013
Revises: 20260610_0012
Create Date: 2026-06-20
"""

from __future__ import annotations

from alembic import op

from app.db.migration_util import index_exists


revision = "20260620_0013"
down_revision = "20260610_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not index_exists("parcel_scores", "ix_parcel_scores_profile_total_created_parcel"):
        op.execute(
            """
            CREATE INDEX ix_parcel_scores_profile_total_created_parcel
            ON parcel_scores (score_profile, total_score DESC, created_at DESC, parcel_id)
            """,
        )


def downgrade() -> None:
    if index_exists("parcel_scores", "ix_parcel_scores_profile_total_created_parcel"):
        op.drop_index("ix_parcel_scores_profile_total_created_parcel", table_name="parcel_scores")
