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

import sys
from pathlib import Path

from db_url_merge import merge_database_url_into_deploy_env


def main() -> int:
    args = [a for a in sys.argv[1:] if a]
    repo = Path(args[0]).resolve() if args else Path("/opt/workspaces/parkinglot")
    env_path = repo / "deploy" / ".env"
    if not env_path.is_file():
        print(f"Missing {env_path}", file=sys.stderr)
        return 1

    print(
        "Copy ONE line from DigitalOcean "
        "(full postgresql://… URI from Connection details — often the **Copy** button).\n"
        "Paste it below and press Enter.\n"
    )
    raw = input().strip()
    try:
        removed, backup = merge_database_url_into_deploy_env(repo, raw)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(f"Backup: {backup}")
    print(f"Updated DATABASE_URL ({removed} old line(s) replaced).")
    print("Next: GitHub → Actions → Deploy to Droplet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
