"""Add OSM commercial POI count for demand-based revenue occupancy.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.migration_util import column_exists

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("parcels", "poi_commercial_count_400m"):
        op.add_column("parcels", sa.Column("poi_commercial_count_400m", sa.Integer(), nullable=True))


def downgrade() -> None:
    if column_exists("parcels", "poi_commercial_count_400m"):
        op.drop_column("parcels", "poi_commercial_count_400m")
