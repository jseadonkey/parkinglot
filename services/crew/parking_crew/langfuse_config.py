"""Hardwired Langfuse US endpoint for parkinglot (see config/langfuse.yaml)."""

from __future__ import annotations

from pathlib import Path

import yaml

from parking_crew.runtime import repo_root

_DEFAULT_US_BASE_URL = "https://us.cloud.langfuse.com"


def langfuse_base_url() -> str:
    """Return the canonical Langfuse API base URL (US cloud)."""
    path = repo_root() / "config" / "langfuse.yaml"
    if path.is_file():
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            url = (raw.get("base_url") or "").strip()
            if url:
                return url.rstrip("/")
    return _DEFAULT_US_BASE_URL


def apply_langfuse_host_env() -> str:
    """Set LANGFUSE_BASE_URL and LANGFUSE_HOST to the hardwired US URL."""
    import os

    url = langfuse_base_url()
    os.environ["LANGFUSE_BASE_URL"] = url
    os.environ["LANGFUSE_HOST"] = url
    return url
