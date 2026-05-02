#!/usr/bin/env python3
"""Run ON the Droplet. Sets DATABASE_URL from ONE pasted line (easiest path).

In DigitalOcean → your database → Connection details: use **Copy** if it copies a
full `postgresql://...` URI (one line). Paste into this script when asked.

If Copy only gives separate fields, use `droplet_set_database_url.py` instead.

Usage:
  python3 scripts/droplet_paste_database_uri.py
  python3 scripts/droplet_paste_database_uri.py /opt/workspaces/parkinglot
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse


def main() -> int:
    args = [a for a in sys.argv[1:] if a]
    repo = Path(args[0]).resolve() if args else Path("/opt/workspaces/parkinglot")
    env_path = repo / "deploy" / ".env"
    if not env_path.is_file():
        print(f"Missing {env_path}", file=sys.stderr)
        return 1

    print(
        "Copy ONE line from DigitalOcean (full postgresql://… URI from Connection details — often the **Copy** button).\n"
        "Paste it below and press Enter.\n"
    )
    raw = input().strip()
    if raw.startswith("DATABASE_URL="):
        raw = raw.split("=", 1)[1].strip()

    u = urlparse(raw)
    if u.scheme not in ("postgresql", "postgres"):
        print(f"Expected postgresql:// URL, got scheme={u.scheme!r}", file=sys.stderr)
        return 1

    # SQLAlchemy/psycopg driver prefix
    fixed = urlunparse(("postgresql+psycopg", u.netloc, u.path, "", u.query, u.fragment))
    new_line = f"DATABASE_URL={fixed}"

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = env_path.with_suffix(f".env.bak.{stamp}")
    shutil.copy2(env_path, backup)
    print(f"Backup: {backup}")

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

    print(f"Updated DATABASE_URL ({removed} old line(s) replaced).")
    print("Next: GitHub → Actions → Deploy to Droplet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
