from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.schemas import ServiceStatusResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ServiceStatusResponse)
def health() -> ServiceStatusResponse:
    return ServiceStatusResponse(status="ok", version=get_settings().app_version)


@router.get("/ready", response_model=ServiceStatusResponse)
def ready(db: Session = Depends(get_db)) -> ServiceStatusResponse:
    """Process is up and can reach Postgres (use for load balancers / uptime checks)."""
    db.execute(text("SELECT 1"))
    return ServiceStatusResponse(status="ready", version=get_settings().app_version)
