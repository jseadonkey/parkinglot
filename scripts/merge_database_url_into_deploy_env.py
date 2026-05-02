#!/usr/bin/env python3
"""Merge DATABASE_URL into deploy/.env — stdin (piped) or argument.

Examples:
  printf '%s' "$URI" | python3 scripts/merge_database_url_into_deploy_env.py
  python3 scripts/merge_database_url_into_deploy_env.py <<< 'postgresql://...'
  python3 scripts/merge_database_url_into_deploy_env.py /opt/workspaces/parkinglot <<< 'postgresql://...'
"""
from __future__ import annotations

import sys
from pathlib import Path

from db_url_merge import merge_database_url_into_deploy_env


def main() -> int:
    repo = Path("/opt/workspaces/parkinglot")
    i = 1
    if len(sys.argv) > i and sys.argv[i].startswith("/"):
        repo = Path(sys.argv[i]).resolve()
        i += 1
    if len(sys.argv) > i:
        raw = sys.argv[i]
    else:
        raw = sys.stdin.read()

    raw = (raw or "").strip()
    if not raw:
        print(
            "Pipe a postgresql:// URI (or DATABASE_URL=...) on stdin.\n"
            "Example: printf '%s' \"$DEPLOY_DATABASE_URL\" | python3 scripts/merge_database_url_into_deploy_env.py",
            file=sys.stderr,
        )
        return 1

    try:
        removed, backup = merge_database_url_into_deploy_env(repo, raw)
    except FileNotFoundError as e:
        print(f"Missing env file: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(f"Backup: {backup}")
    print(f"Updated DATABASE_URL ({removed} old line(s) replaced) in {repo / 'deploy' / '.env'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
