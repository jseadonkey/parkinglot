"""Compatibility revision for production databases already stamped 20260610_0012.

Revision ID: 20260610_0012
Revises: 20260607_0010
Create Date: 2026-06-10

Production was stamped to ``20260610_0012`` without this revision file being
present in main. Keep this no-op revision so Alembic can resolve that stamp and
the API container can boot.
"""

from __future__ import annotations

revision = "20260610_0012"
down_revision = "20260607_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
