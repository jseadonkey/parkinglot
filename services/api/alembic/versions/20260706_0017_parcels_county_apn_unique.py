"""Unique (county_fips, apn) on parcels — prevents concurrent ingest duplicates.

Revision ID: 20260706_0017
Revises: 20260621_0015
Create Date: 2026-07-06

"""

from typing import Sequence, Union

from alembic import op

from app.db.migration_util import index_exists

revision: str = "20260706_0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if index_exists("parcels", "ix_parcels_county_apn"):
        op.drop_index("ix_parcels_county_apn", table_name="parcels")
    if not index_exists("parcels", "uq_parcels_county_apn"):
        op.create_index(
            "uq_parcels_county_apn",
            "parcels",
            ["county_fips", "apn"],
            unique=True,
        )


def downgrade() -> None:
    if index_exists("parcels", "uq_parcels_county_apn"):
        op.drop_index("uq_parcels_county_apn", table_name="parcels")
    if not index_exists("parcels", "ix_parcels_county_apn"):
        op.create_index(
            "ix_parcels_county_apn",
            "parcels",
            ["county_fips", "apn"],
            unique=False,
        )
