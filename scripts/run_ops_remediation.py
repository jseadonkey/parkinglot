#!/usr/bin/env python3
"""Run ops remediation loop synchronously (no Celery).

  python3 scripts/run_ops_remediation.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
os.chdir(ROOT)

_env_file = ROOT / "deploy" / ".env"
if _env_file.is_file():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val

os.environ.setdefault("OPS_REMEDIATION_ENABLED", "true")
os.environ.setdefault("OPS_REMEDIATION_AUTO_FIX", "true")
os.environ.setdefault("PILOT_CONFIG_PATH", str(ROOT / "config" / "pilot.yaml"))

from app.db.session import SessionLocal  # noqa: E402
from app.ops_remediation import run_ops_remediation_loop  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        report = run_ops_remediation_loop(db)
        print(json.dumps(report, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
