"""Add default SMS / text outreach template row.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.migration_util import table_exists

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_SMS = """Hi {{ owner_name }} — {{ sender_company }} here. We are exploring a ground lease for surface parking at APN {{ apn }} in {{ region_name }}. Open to a brief call? {{ sender_phone }}

DRAFT — REQUIRES COUNSEL AND HUMAN APPROVAL BEFORE SENDING. Reply STOP to opt out."""


def upgrade() -> None:
    if not table_exists("outreach_templates"):
        return
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM outreach_templates WHERE slug = :slug"),
        {"slug": "sms_outreach"},
    ).fetchone()
    if exists:
        return
    templates = sa.table(
        "outreach_templates",
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("channel", sa.String),
        sa.column("subject", sa.String),
        sa.column("body", sa.Text),
    )
    op.bulk_insert(
        templates,
        [
            {
                "slug": "sms_outreach",
                "name": "Text message (SMS)",
                "channel": "sms",
                "subject": None,
                "body": _DEFAULT_SMS,
            },
        ],
    )


def downgrade() -> None:
    if not table_exists("outreach_templates"):
        return
    op.execute(sa.text("DELETE FROM outreach_templates WHERE slug = 'sms_outreach'"))
