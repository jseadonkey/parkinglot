"""Display sources for licensed vendor / skip-trace enrichment."""

from __future__ import annotations

SKIP_TRACE_SOURCE = "skip_trace"


def vendor_provider_to_source(provider: str | None) -> str:
    """Map stored vendor provider id to operator-facing contact source."""
    p = (provider or "").strip().lower()
    if p in ("batchdata", "skip_trace"):
        return SKIP_TRACE_SOURCE
    return p or "vendor"
