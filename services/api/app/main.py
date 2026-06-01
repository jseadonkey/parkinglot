from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import approvals, audit, health, internal, outreach, outreach_templates, parcels, workflows


def _cors_origins() -> list[str]:
    raw = get_settings().cors_allow_origins.strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


app = FastAPI(title="Parking acquisition agents API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(parcels.router)
app.include_router(outreach.router)
app.include_router(outreach_templates.router)
app.include_router(approvals.router)
app.include_router(audit.router)
app.include_router(workflows.router)
app.include_router(internal.router)
