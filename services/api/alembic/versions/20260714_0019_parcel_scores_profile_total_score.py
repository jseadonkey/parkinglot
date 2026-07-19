"""Index parcel_scores for operator top-N score lists.

Revision ID: 20260714_0019
Revises: 20260707_0018
Create Date: 2026-07-14
"""

from __future__ import annotations

from alembic import op

from app.db.migration_util import index_exists

revision = "20260714_0019"
down_revision = "20260707_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not index_exists("parcel_scores", "ix_parcel_scores_profile_total_score"):
        op.create_index(
            "ix_parcel_scores_profile_total_score",
            "parcel_scores",
            ["score_profile", "total_score"],
            postgresql_ops={"total_score": "DESC NULLS LAST"},
        )


def downgrade() -> None:
    if index_exists("parcel_scores", "ix_parcel_scores_profile_total_score"):
        op.drop_index("ix_parcel_scores_profile_total_score", table_name="parcel_scores")
