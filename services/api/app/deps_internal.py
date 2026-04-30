from __future__ import annotations

from fastapi import Header, HTTPException

from app.config import get_settings


def require_internal_key(x_internal_key: str | None = Header(default=None, alias="X-Internal-Key")) -> None:
    expected = (get_settings().internal_api_key or "").strip()
    if not expected:
        return
    if (x_internal_key or "").strip() != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
