"""parcels.owner_outreach_brief JSONB (pipeline persistence)

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-01

"""

from typing import Union
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.db.migration_util import column_exists

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not column_exists("parcels", "owner_outreach_brief"):
        op.add_column("parcels", sa.Column("owner_outreach_brief", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("parcels", "owner_outreach_brief")
