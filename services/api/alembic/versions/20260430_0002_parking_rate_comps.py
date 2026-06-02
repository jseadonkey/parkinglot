"""parking_rate_comps table for spatial rate benchmarks

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-30

"""

from typing import Union
from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.db.migration_util import table_exists

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if table_exists("parking_rate_comps"):
        return
    op.create_table(
        "parking_rate_comps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("hourly_mid_usd", sa.Float(), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "location",
            geoalchemy2.types.Geometry(geometry_type="POINT", srid=4326, dimension=2),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute("CREATE INDEX ix_parking_rate_comps_location ON parking_rate_comps USING GIST (location)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_parking_rate_comps_location")
    op.drop_table("parking_rate_comps")
