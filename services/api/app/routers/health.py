from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": get_settings().app_version}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    """Process is up and can reach Postgres (use for load balancers / uptime checks)."""
    db.execute(text("SELECT 1"))
    return {"status": "ready", "version": get_settings().app_version}
