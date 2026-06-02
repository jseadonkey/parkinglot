"""Merge alembic heads (score-profile branch + rate-comps/outreach branch).

Revision ID: 0006
Revises: 0005, 20260502_0003
Create Date: 2026-05-31

"""

from typing import Union
from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = ("0005", "20260502_0003")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
