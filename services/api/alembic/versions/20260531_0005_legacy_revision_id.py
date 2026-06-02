"""Legacy Alembic revision id used on some production DBs (filename-style stamp).

Revision ID: 20260531_0005
Revises: 0004
Create Date: 2026-06-01

Production may have ``alembic_version.version_num = '20260531_0005'`` without this file;
the real schema change lives in revision ``0005`` (next in chain).

"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260531_0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
