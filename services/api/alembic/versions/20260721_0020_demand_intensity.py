"""Weighted parking-demand intensity (anchor magnitude, not POI count).

Revision ID: 20260721_0020
Revises: 20260714_0019
Create Date: 2026-07-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.migration_util import column_exists

revision = "20260721_0020"
down_revision = "20260714_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not column_exists("parcels", "poi_demand_intensity"):
        op.add_column("parcels", sa.Column("poi_demand_intensity", sa.Float(), nullable=True))
    if not column_exists("parcels", "poi_heavy_anchor_count"):
        op.add_column("parcels", sa.Column("poi_heavy_anchor_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    if column_exists("parcels", "poi_heavy_anchor_count"):
        op.drop_column("parcels", "poi_heavy_anchor_count")
    if column_exists("parcels", "poi_demand_intensity"):
        op.drop_column("parcels", "poi_demand_intensity")
