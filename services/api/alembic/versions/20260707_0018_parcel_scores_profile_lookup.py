"""Index parcel_scores for latest-score DISTINCT ON scans.

Revision ID: 20260707_0018
Revises: 20260706_0017
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op

from app.db.migration_util import index_exists

revision = "20260707_0018"
down_revision = "20260706_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not index_exists("parcel_scores", "ix_parcel_scores_profile_parcel_created_at"):
        op.create_index(
            "ix_parcel_scores_profile_parcel_created_at",
            "parcel_scores",
            ["score_profile", "parcel_id", "created_at"],
        )


def downgrade() -> None:
    if index_exists("parcel_scores", "ix_parcel_scores_profile_parcel_created_at"):
        op.drop_index("ix_parcel_scores_profile_parcel_created_at", table_name="parcel_scores")
