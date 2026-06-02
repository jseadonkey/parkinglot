"""Ensure parking_rate_comps exists (repair branch that was skipped on some deploys).

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-02

"""

from typing import Sequence, Union

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from app.db.migration_util import table_exists

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    if not table_exists("parking_rate_comps"):
        return
    op.execute("DROP INDEX IF EXISTS ix_parking_rate_comps_location")
    op.drop_table("parking_rate_comps")
