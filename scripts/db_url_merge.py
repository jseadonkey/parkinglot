"""Shared helpers to write DATABASE_URL into deploy/.env (used by CLI + GitHub Actions)."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse


def normalize_raw_to_env_line(raw: str) -> str:
    """Turn pasted URI or DATABASE_URL= line into a single DATABASE_URL= line with psycopg driver."""
    raw = raw.strip()
    if raw.startswith("DATABASE_URL="):
        raw = raw.split("=", 1)[1].strip()

    u = urlparse(raw)
    if u.scheme not in ("postgresql", "postgres", "postgresql+psycopg"):
        raise ValueError(f"Expected postgresql URL, got scheme={u.scheme!r}")

    if u.scheme == "postgresql+psycopg":
        return f"DATABASE_URL={raw}"

    fixed = urlunparse(("postgresql+psycopg", u.netloc, u.path, "", u.query, u.fragment))
    return f"DATABASE_URL={fixed}"


def merge_database_url_into_deploy_env(repo_root: Path, raw_connection: str) -> tuple[int, Path]:
    """
    Replace active DATABASE_URL= lines in deploy/.env. Backs up first.
    Returns (number of replaced lines, backup_path).
    """
    env_path = repo_root / "deploy" / ".env"
    if not env_path.is_file():
        raise FileNotFoundError(env_path)

    new_line = normalize_raw_to_env_line(raw_connection)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = env_path.with_suffix(f".env.bak.{stamp}")
    shutil.copy2(env_path, backup)

    text = env_path.read_text(encoding="utf-8")
    lines_out: list[str] = []
    removed = 0
    for line in text.splitlines():
        if line.startswith("DATABASE_URL="):
            removed += 1
            continue
        lines_out.append(line)
    while lines_out and lines_out[-1].strip() == "":
        lines_out.pop()
    lines_out.append(new_line)
    lines_out.append("")
    env_path.write_text("\n".join(lines_out), encoding="utf-8")
    return removed, backup
