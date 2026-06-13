"""Compatibility revision for production databases already stamped 0011.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-06

Some production deploys were stamped to ``0011`` without the revision file being
present in the repo. Keep this no-op revision so Alembic can resolve that stamp.
"""

from typing import Sequence, Union

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
