"""Parcel pilot_in_scope flag for King/Kent geographic filter.

Revision ID: 20260531_0004
Revises: 20260502_0003
Create Date: 2026-05-31

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260531_0004"
down_revision = "20260502_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parcels",
        sa.Column("pilot_in_scope", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_parcels_pilot_in_scope", "parcels", ["pilot_in_scope"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_parcels_pilot_in_scope", table_name="parcels")
    op.drop_column("parcels", "pilot_in_scope")
