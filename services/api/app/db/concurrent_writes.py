"""Small commits and deadlock retries for batch jobs that run beside live workers."""

from __future__ import annotations

import random
import time
import uuid
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import ColumnElement, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

T = TypeVar("T")


def is_deadlock_error(exc: BaseException) -> bool:
    if isinstance(exc, OperationalError):
        orig = getattr(exc, "orig", None)
        if orig is not None and orig.__class__.__name__ == "DeadlockDetected":
            return True
        return "DeadlockDetected" in str(exc)
    return False


def retry_on_deadlock(
    fn: Callable[[], T],
    *,
    max_retries: int = 6,
    base_delay_sec: float = 0.05,
) -> T:
    """Run ``fn``; on Postgres deadlock, rollback is caller's duty before retrying."""
    last: BaseException | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except OperationalError as exc:
            if not is_deadlock_error(exc) or attempt >= max_retries - 1:
                raise
            last = exc
            delay = base_delay_sec * (2**attempt) + random.random() * base_delay_sec
            time.sleep(delay)
    if last is not None:
        raise last
    raise RuntimeError("retry_on_deadlock: unreachable")


def update_parcel_columns_if(
    db: Session,
    parcel_id: uuid.UUID,
    values: dict[str, object],
    *where_extra: ColumnElement[bool],
    max_retries: int = 6,
) -> bool:
    """Single-row UPDATE in its own commit; safe when other workers touch other parcels."""

    from app.db.models import Parcel

    def _run() -> bool:
        stmt = update(Parcel).where(Parcel.id == parcel_id, *where_extra).values(**values)
        result = db.execute(stmt)
        db.commit()
        return (result.rowcount or 0) > 0

    try:
        return retry_on_deadlock(_run, max_retries=max_retries)
    except OperationalError:
        db.rollback()
        raise
