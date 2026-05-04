#!/usr/bin/env python3
"""Run ON the Droplet after SSH — sets DATABASE_URL in deploy/.env from prompts.

You only need:
  - Host, user, database name, port from DigitalOcean → Databases → Connection details
  - Password (typed hidden)

Does not print your password. Backs up .env before changing.

Usage:
  python3 scripts/droplet_set_database_url.py
  python3 scripts/droplet_set_database_url.py /opt/parking-acquisition-agents
"""
from __future__ import annotations

import getpass
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote


def main() -> int:
    repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path("/opt/parking-acquisition-agents")
    env_path = repo / "deploy" / ".env"
    if not env_path.is_file():
        print(
            f"Missing {env_path} — create it first, e.g.: cp deploy/secrets.env.example deploy/secrets.env "
            f"(fill secrets), then python3 scripts/render_deploy_env.py — or cp {repo / 'deploy' / 'env.production.example'} "
            f"{env_path}",
            file=sys.stderr,
        )
        return 1

    print("Have DigitalOcean open: Databases → your cluster → Connection details.\n")
    host = input("Host (long name ending in .db.ondigitalocean.com): ").strip()
    if not host:
        print("Host is required.", file=sys.stderr)
        return 1
    user = (input("Database user [doadmin]: ").strip() or "doadmin")
    db = (input("Database name [defaultdb]: ").strip() or "defaultdb")
    port = (input("Port [25060]: ").strip() or "25060")

    password = (os.environ.get("DO_DB_PASSWORD") or "").strip()
    if password:
        print("(Using password from environment variable DO_DB_PASSWORD. Run: unset DO_DB_PASSWORD  when finished.)\n")
    else:
        password = getpass.getpass("Database password (hidden, no characters will show): ")
        if not password:
            print(
                "No password was received. Common fix: in DigitalOcean click **show** next to the password, "
                "copy it, then in this terminal use the **Edit** menu → **Paste** "
                "(or right‑click → Paste) at the password prompt, then Enter.\n",
                file=sys.stderr,
            )
            password = getpass.getpass("Database password (try again, hidden): ")
    if not password:
        print(
            "Password is still empty. You can run once with the password in the environment "
            "(only you on the server), then unset it:\n"
            "  DO_DB_PASSWORD='paste-from-DO-here' python3 scripts/droplet_set_database_url.py\n"
            "  unset DO_DB_PASSWORD",
            file=sys.stderr,
        )
        return 1

    enc = quote(password, safe="")
    new_line = f"DATABASE_URL=postgresql+psycopg://{user}:{enc}@{host}:{port}/{db}?sslmode=require"

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
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

    print(f"Updated DATABASE_URL in {env_path} (replaced {removed} previous active line(s)).")
    print("Next: GitHub → Actions → Deploy to Droplet → Re-run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
