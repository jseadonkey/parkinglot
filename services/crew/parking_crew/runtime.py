"""Detect whether code is running on the parkinglot Droplet vs a local Mac clone."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """Walk up from this file to the parkinglot monorepo root."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config" / "pilot.yaml").is_file() and (parent / "services" / "api").is_dir():
            return parent
    return here.parents[2]


def is_droplet_runtime() -> bool:
    """
    True when running on the production Droplet workspace (/opt/workspaces/parkinglot).

    Override for tests: PARKINGLOT_RUNTIME=droplet|local
    """
    forced = (os.getenv("PARKINGLOT_RUNTIME") or "").strip().lower()
    if forced == "droplet":
        return True
    if forced == "local":
        return False

    root = repo_root()
    if str(root).startswith("/opt/workspaces/parkinglot"):
        return True

    deploy_env = root / "deploy" / ".env"
    if deploy_env.is_file():
        try:
            text = deploy_env.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        # Managed Postgres on DO — never use Mac localhost DB in production.
        if "ondigitalocean.com" in text or "db-postgresql" in text:
            return True
        if "PUBLIC_API_URL=https://" in text and "localhost" not in text.split("PUBLIC_API_URL=", 1)[-1][:80]:
            return True

    return False


def runtime_label() -> str:
    return "droplet" if is_droplet_runtime() else "local"
