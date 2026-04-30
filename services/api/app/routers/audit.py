from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLog
from app.db.session import get_db
from app.schemas import AuditRead

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditRead])
def list_audit(limit: int = 100, db: Session = Depends(get_db)) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 500))
    return list(db.scalars(stmt))
