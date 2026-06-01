"""Idempotent Alembic upgrade helpers (importable as ``app.db.migration_util``)."""

from __future__ import annotations

from sqlalchemy import inspect

from alembic import op


def table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def column_exists(table: str, column: str) -> bool:
    cols = inspect(op.get_bind()).get_columns(table)
    return any(c.get("name") == column for c in cols)


def index_exists(table: str, index_name: str) -> bool:
    for idx in inspect(op.get_bind()).get_indexes(table):
        if idx.get("name") == index_name:
            return True
    return False
