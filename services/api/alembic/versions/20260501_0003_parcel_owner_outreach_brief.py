"""parcels.owner_outreach_brief JSONB (pipeline persistence)

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("parcels", sa.Column("owner_outreach_brief", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("parcels", "owner_outreach_brief")
