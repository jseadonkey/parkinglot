"""Gate owner outreach drafts behind a human contact decision.

Revision ID: 20260607_0011
Revises: 20260607_0010
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.migration_util import column_exists


revision = "20260607_0011"
down_revision = "20260607_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not column_exists("parcels", "owner_contact_decision"):
        op.add_column(
            "parcels",
            sa.Column(
                "owner_contact_decision",
                sa.String(length=32),
                nullable=False,
                server_default="pending",
            ),
        )
    if not column_exists("parcels", "owner_contact_decision_by"):
        op.add_column("parcels", sa.Column("owner_contact_decision_by", sa.String(length=256), nullable=True))
    if not column_exists("parcels", "owner_contact_decision_at"):
        op.add_column("parcels", sa.Column("owner_contact_decision_at", sa.DateTime(timezone=True), nullable=True))
    if not column_exists("parcels", "owner_contact_decision_note"):
        op.add_column("parcels", sa.Column("owner_contact_decision_note", sa.Text(), nullable=True))


def downgrade() -> None:
    for column in (
        "owner_contact_decision_note",
        "owner_contact_decision_at",
        "owner_contact_decision_by",
        "owner_contact_decision",
    ):
        if column_exists("parcels", column):
            op.drop_column("parcels", column)
