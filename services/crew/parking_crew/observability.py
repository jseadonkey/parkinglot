"""Optional Langfuse tracing for CrewAI runs (keys stay in .env — never commit)."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator

from parking_crew.langfuse_config import apply_langfuse_host_env, langfuse_base_url


def langfuse_configured() -> bool:
    public_key = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
    secret_key = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip()
    return bool(public_key and secret_key)


def _normalize_langfuse_host() -> None:
    """Always use hardwired US URL from config/langfuse.yaml."""
    apply_langfuse_host_env()


def _clean_langfuse_keys() -> None:
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        val = (os.getenv(key) or "").strip().strip('"').strip("'")
        if val:
            os.environ[key] = val


def setup_langfuse_instrumentation() -> bool:
    """
    Register CrewAI OpenInference instrumentation when Langfuse keys are present.
    Returns True when tracing is active.
    """
    if not langfuse_configured():
        return False

    _normalize_langfuse_host()

    try:
        from openinference.instrumentation.crewai import CrewAIInstrumentor
    except ImportError:
        return False

    CrewAIInstrumentor().instrument(skip_dep_check=True)
    return True


def verify_langfuse_connection() -> dict[str, Any]:
    """Check Langfuse auth without printing secret values."""
    if not langfuse_configured():
        return {
            "configured": False,
            "authenticated": False,
            "message": "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in services/crew/.env",
        }

    _clean_langfuse_keys()
    _normalize_langfuse_host()
    host = langfuse_base_url()
    public_key = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
    masked_public = f"{public_key[:8]}…{public_key[-4:]}" if len(public_key) > 12 else "(set)"

    try:
        from langfuse import get_client
    except ImportError:
        return {
            "configured": True,
            "authenticated": False,
            "host": host,
            "public_key": masked_public,
            "message": 'Install observability extras: pip install "./services/crew[observability]"',
        }

    try:
        from langfuse import get_client

        client = get_client()
        ok = bool(client.auth_check())
    except Exception as exc:
        err = str(exc)
        hint = "Auth failed — regenerate keys in Langfuse → Project Settings → API Keys (same project)."
        if "correct host" in err.lower():
            hint = (
                "Auth failed on all regions usually means wrong or revoked keys, not the host. "
                "Create new Project API keys in Langfuse and re-run droplet-crew-langfuse-setup.sh."
            )
        return {
            "configured": True,
            "authenticated": False,
            "host": host,
            "public_key": masked_public,
            "message": hint,
            "error": type(exc).__name__,
        }

    return {
        "configured": True,
        "authenticated": ok,
        "host": host,
        "public_key": masked_public,
        "message": "Langfuse ready" if ok else "Auth failed — check keys and LANGFUSE_HOST / LANGFUSE_BASE_URL region",
    }


def flush_langfuse() -> None:
    if not langfuse_configured():
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        pass


@contextmanager
def langfuse_crew_trace(name: str, *, metadata: dict[str, Any] | None = None) -> Generator[None, None, None]:
    """Wrap a crew kickoff in a Langfuse span when configured."""
    if not langfuse_configured():
        yield
        return

    _normalize_langfuse_host()
    try:
        from langfuse import get_client
    except ImportError:
        yield
        return

    client = get_client()
    with client.start_as_current_observation(as_type="span", name=name, metadata=metadata or {}):
        try:
            yield
        finally:
            flush_langfuse()
