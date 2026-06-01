"""Add score_profile to parcel_scores for dual scoring agents.

Revision ID: 20260501_0002
Revises: 20260429_0001
Create Date: 2026-05-01

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.migration_util import column_exists, index_exists

revision = "20260501_0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not column_exists("parcel_scores", "score_profile"):
        op.add_column(
            "parcel_scores",
            sa.Column("score_profile", sa.String(length=32), nullable=False, server_default="entitlement"),
        )
        op.alter_column("parcel_scores", "score_profile", server_default=None)
    if not index_exists("parcel_scores", "ix_parcel_scores_parcel_id_profile"):
        op.create_index(
            "ix_parcel_scores_parcel_id_profile",
            "parcel_scores",
            ["parcel_id", "score_profile"],
        )


def downgrade() -> None:
    op.drop_index("ix_parcel_scores_parcel_id_profile", table_name="parcel_scores")
    op.drop_column("parcel_scores", "score_profile")
