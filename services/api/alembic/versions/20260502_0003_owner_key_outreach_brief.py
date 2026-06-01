"""Owner rollup key + parcel.owner_outreach_brief JSONB.

Revision ID: 20260502_0003
Revises: 20260501_0002
Create Date: 2026-05-02

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.db.migration_util import column_exists, index_exists

revision = "20260502_0003"
down_revision = "20260501_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not column_exists("parcels", "owner_outreach_brief"):
        op.add_column("parcels", sa.Column("owner_outreach_brief", JSONB(), nullable=True))
    if not column_exists("owner_candidates", "normalized_owner_key"):
        op.add_column(
            "owner_candidates",
            sa.Column("normalized_owner_key", sa.String(length=256), nullable=True),
        )
    if not index_exists("owner_candidates", "ix_owner_candidates_normalized_owner_key"):
        op.create_index(
            "ix_owner_candidates_normalized_owner_key",
            "owner_candidates",
            ["normalized_owner_key"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_owner_candidates_normalized_owner_key", table_name="owner_candidates")
    op.drop_column("owner_candidates", "normalized_owner_key")
    op.drop_column("parcels", "owner_outreach_brief")
