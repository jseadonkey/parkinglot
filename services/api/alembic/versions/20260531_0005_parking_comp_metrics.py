"""Parking comp columns on parcels.

Revision ID: 20260531_0005
Revises: 20260531_0004
Create Date: 2026-05-31

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260531_0005"
down_revision = "20260531_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parcels",
        sa.Column("distance_to_nearest_comp_parking_m", sa.Float(), nullable=True),
    )
    op.add_column(
        "parcels",
        sa.Column("nearest_parking_comp", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("parcels", "nearest_parking_comp")
    op.drop_column("parcels", "distance_to_nearest_comp_parking_m")
