#!/usr/bin/env python3
"""Emit FastAPI OpenAPI schema as JSON (codegen, diff reviews, CI artifacts).

Requires API dependencies on ``PYTHONPATH`` — same as CI (e.g. activate repo ``.venv``
after ``pip install ... ./services/api[dev]``).

  python3 scripts/export_openapi_json.py
  python3 scripts/export_openapi_json.py -o /tmp/openapi.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    from parcel_export_common import ensure_api_path

    parser = argparse.ArgumentParser(description="Export OpenAPI JSON from the FastAPI app")
    parser.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help="Write to file (default: stdout)",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indent (default: 2; use 0 for compact)",
    )
    args = parser.parse_args()

    os.environ.setdefault("APP_VERSION", "openapi-export")

    ensure_api_path()
    from app.main import app  # noqa: PLC0415

    spec = app.openapi()
    indent = None if args.indent == 0 else args.indent
    text = json.dumps(spec, indent=indent) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
