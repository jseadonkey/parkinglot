"""outreach_templates — admin-editable mail / phone / email copy

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-31

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_CERTIFIED_MAIL = """{{ owner_name }}

{{ mailing_address }}

Re: Property APN {{ apn }} (County FIPS {{ county_fips }})

Dear Property Owner,

We are {{ sender_company }}, and we are contacting owners of properties that may be suitable for paid parking use in the {{ region_name }} area.

We would like to explore a ground lease arrangement for surface parking at the above-referenced parcel. This letter is an expression of interest only and is not an offer or contract.

If you are open to a brief conversation, please contact us at {{ sender_phone }} or {{ sender_email }}.

Sincerely,
{{ sender_name }}
{{ sender_company }}

DRAFT — REQUIRES COUNSEL AND HUMAN APPROVAL BEFORE MAILING."""

_DEFAULT_PHONE_SCRIPT = """# Phone call script (read or AI voice)

## Opening
Hello, may I speak with the owner or property manager for the parcel at {{ situs_address or mailing_address }}?

## If wrong party
Thank you for your time. I'll update our records. Goodbye.

## If right party
This is {{ sender_name }} calling on behalf of {{ sender_company }}. We work on ground lease arrangements for surface parking. We're reaching out because your property (APN {{ apn }}) may be a fit for paid parking in {{ region_name }}. Is this something you'd be willing to discuss briefly?

## If not interested
Understood. Thank you for your time. Goodbye.

## If interested
Great — our team can follow up by mail or email with next steps. What's the best way to reach you?

## Operator note
Log the outcome per phone number. Do not discuss specific terms without counsel-approved materials."""

_DEFAULT_EMAIL = """Dear {{ owner_name }},

We are {{ sender_company }}, reaching out regarding your property (APN {{ apn }}, county {{ county_fips }}) in the {{ region_name }} area.

We would like to explore a ground lease for surface parking. This message is an expression of interest only and is not an offer or contract.

If you are open to a brief conversation, please reply or call {{ sender_phone }}.

Sincerely,
{{ sender_name }}
{{ sender_company }}

DRAFT — REQUIRES COUNSEL AND HUMAN APPROVAL BEFORE SENDING."""


def upgrade() -> None:
    op.create_table(
        "outreach_templates",
        sa.Column("slug", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(length=256), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
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
                "slug": "certified_mail_letter",
                "name": "Certified mail letter",
                "channel": "certified_mail",
                "subject": None,
                "body": _DEFAULT_CERTIFIED_MAIL,
            },
            {
                "slug": "phone_call_script",
                "name": "Phone / AI call script",
                "channel": "phone",
                "subject": None,
                "body": _DEFAULT_PHONE_SCRIPT,
            },
            {
                "slug": "email_outreach",
                "name": "Email outreach",
                "channel": "email",
                "subject": "Interest in parking use — APN {{ apn }}",
                "body": _DEFAULT_EMAIL,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("outreach_templates")
