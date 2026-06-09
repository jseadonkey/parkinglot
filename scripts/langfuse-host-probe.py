#!/usr/bin/env python3
"""Verify Langfuse US credentials in deploy/.env."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langfuse import Langfuse

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "services" / "crew"))

from parking_crew.langfuse_config import langfuse_base_url  # noqa: E402

load_dotenv(root / "deploy" / ".env")
load_dotenv(root / "services" / "crew" / ".env", override=False)

host = langfuse_base_url()
print(f"Probing hardwired host: {host}")

pk = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip().strip('"').strip("'")
sk = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip().strip('"').strip("'")
if not pk or not sk:
    print("FAIL: LANGFUSE keys missing")
    raise SystemExit(1)

client = Langfuse(public_key=pk, secret_key=sk, base_url=host)
ok = bool(client.auth_check())
print("OK" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
