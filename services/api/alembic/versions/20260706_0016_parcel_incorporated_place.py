"""Persist incorporated-place classification on parcels.

Revision ID: 0016
Revises: 20260621_0015
Create Date: 2026-07-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.migration_util import column_exists, index_exists

revision: str = "0016"
down_revision: Union[str, None] = "20260621_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("parcels", "is_incorporated"):
        op.add_column("parcels", sa.Column("is_incorporated", sa.Boolean(), nullable=True))
    if not column_exists("parcels", "incorporated_place_geoid"):
        op.add_column("parcels", sa.Column("incorporated_place_geoid", sa.String(length=12), nullable=True))
    if not column_exists("parcels", "incorporated_place_name"):
        op.add_column("parcels", sa.Column("incorporated_place_name", sa.String(length=128), nullable=True))
    if not column_exists("parcels", "zoning_jurisdiction_hint"):
        op.add_column("parcels", sa.Column("zoning_jurisdiction_hint", sa.String(length=64), nullable=True))
    if not index_exists("parcels", "ix_parcels_county_fips_is_incorporated"):
        op.create_index(
            "ix_parcels_county_fips_is_incorporated",
            "parcels",
            ["county_fips", "is_incorporated"],
        )


def downgrade() -> None:
    if index_exists("parcels", "ix_parcels_county_fips_is_incorporated"):
        op.drop_index("ix_parcels_county_fips_is_incorporated", table_name="parcels")
    if column_exists("parcels", "zoning_jurisdiction_hint"):
        op.drop_column("parcels", "zoning_jurisdiction_hint")
    if column_exists("parcels", "incorporated_place_name"):
        op.drop_column("parcels", "incorporated_place_name")
    if column_exists("parcels", "incorporated_place_geoid"):
        op.drop_column("parcels", "incorporated_place_geoid")
    if column_exists("parcels", "is_incorporated"):
        op.drop_column("parcels", "is_incorporated")
