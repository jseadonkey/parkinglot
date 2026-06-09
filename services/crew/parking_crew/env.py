"""Resolve crew credentials — Droplet-first (deploy/.env is source of truth on server)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from parking_crew.langfuse_config import apply_langfuse_host_env
from parking_crew.runtime import is_droplet_runtime, repo_root


def crew_root() -> Path:
    """Directory containing config/agents.yaml (works for editable and site-packages installs)."""
    root = repo_root()
    candidate = root / "services" / "crew"
    if (candidate / "config" / "agents.yaml").is_file():
        return candidate
    return Path(__file__).resolve().parent.parent


# Keys the crew reads directly or via aliases below.
CREW_SECRET_KEYS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "CREWAI_LLM",
    "CREW_DATABASE_URL",
    "DATABASE_URL",
    "SERPER_API_KEY",
    "TAVILY_API_KEY",
    "GITHUB_TOKEN",
    "GITHUB_REPO",
    "GITHUB_BASE_BRANCH",
    "SLACK_BOT_TOKEN",
    "SLACK_ADMIN_CHANNEL_ID",
    "SLACK_DIGEST_CHANNEL_ID",
    "SLACK_AGENT_DISCUSSION_CHANNEL_ID",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
    "LANGFUSE_BASE_URL",
    "FINOPS_LOG_COMMAND",
    "FINOPS_DB_STATS_COMMAND",
    "FINOPS_SSH_HOST",
    "FINOPS_SSH_USER",
    "INTERNAL_API_KEY",
    "BATCHDATA_API_KEY",
)


def _env_file_paths() -> tuple[Path, ...]:
    """
    Droplet: deploy/.env first (production secrets), then services/crew/.env overrides.
    Local Mac: optional crew/.env + deploy/.env mirror; repo .env last.
    """
    root = repo_root()
    crew_env = crew_root() / ".env"
    deploy_env = root / "deploy" / ".env"
    repo_env = root / ".env"

    if is_droplet_runtime():
        paths: list[Path] = []
        if deploy_env.is_file():
            paths.append(deploy_env)
        if crew_env.is_file():
            paths.append(crew_env)
        return tuple(paths)

    paths = []
    if crew_env.is_file():
        paths.append(crew_env)
    if deploy_env.is_file():
        paths.append(deploy_env)
    if repo_env.is_file():
        paths.append(repo_env)
    paths.append(Path.home() / ".config" / "parkinglot" / "env")
    return tuple(paths)


def load_crew_env() -> None:
    """Load credentials; on Droplet never fall back to localhost Postgres."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        _apply_credential_aliases()
        return

    for path in _env_file_paths():
        if path.is_file():
            load_dotenv(path, override=False)

    _apply_credential_aliases()


def _first_non_empty(*keys: str) -> str | None:
    for key in keys:
        val = (os.getenv(key) or "").strip()
        if val:
            return val
    return None


def _setdefault_env(key: str, value: str | None) -> None:
    if value and not (os.getenv(key) or "").strip():
        os.environ[key] = value


def _detect_github_repo() -> str | None:
    existing = (os.getenv("GITHUB_REPO") or "").strip()
    if existing:
        return existing
    root = repo_root()
    try:
        url = subprocess.check_output(
            ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if url.startswith("git@"):
        path = url.split(":", 1)[-1]
    else:
        path = url.rsplit("/", 2)[-2] + "/" + url.rsplit("/", 1)[-1]
    path = path.removesuffix(".git")
    return path or None


def _apply_credential_aliases() -> None:
    """Map parkinglot stack credentials onto crew tool names."""
    _setdefault_env("CREW_DATABASE_URL", _first_non_empty("CREW_DATABASE_URL", "DATABASE_URL"))
    _setdefault_env("DATABASE_URL", _first_non_empty("DATABASE_URL", "CREW_DATABASE_URL"))

    _setdefault_env(
        "SLACK_ADMIN_CHANNEL_ID",
        _first_non_empty(
            "SLACK_ADMIN_CHANNEL_ID",
            "SLACK_AGENT_DISCUSSION_CHANNEL_ID",
            "SLACK_DIGEST_CHANNEL_ID",
        ),
    )

    _setdefault_env("GITHUB_REPO", _detect_github_repo())
    _setdefault_env("GITHUB_BASE_BRANCH", _first_non_empty("GITHUB_BASE_BRANCH") or "main")

    # Langfuse US cloud — hardwired in config/langfuse.yaml (not from browser or EU default).
    apply_langfuse_host_env()

    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        val = (os.getenv(key) or "").strip().strip('"').strip("'")
        if val:
            os.environ[key] = val

    _setdefault_env("GITHUB_REPO", _detect_github_repo())
    _setdefault_env("GITHUB_BASE_BRANCH", _first_non_empty("GITHUB_BASE_BRANCH") or "main")

    if is_droplet_runtime():
        # Logs and compose are on this host — never SSH to ourselves.
        os.environ.pop("FINOPS_SSH_HOST", None)
        os.environ.setdefault(
            "FINOPS_LOG_COMMAND",
            "docker compose -f deploy/docker-compose.production.yml logs --since {lookback_hours}h api worker beat",
        )
    else:
        if not (os.getenv("CREW_DATABASE_URL") or os.getenv("DATABASE_URL")):
            os.environ.setdefault(
                "DATABASE_URL",
                "postgresql+psycopg://parking:parking@127.0.0.1:5432/parking",
            )
        if not (os.getenv("FINOPS_LOG_COMMAND") or "").strip():
            os.environ.setdefault(
                "FINOPS_LOG_COMMAND",
                "docker compose -f deploy/docker-compose.production.yml logs --since {lookback_hours}h api worker beat",
            )


def configured_secret_keys() -> dict[str, bool]:
    """Return which credential names are set (never returns values)."""
    load_crew_env()
    return {key: bool((os.getenv(key) or "").strip()) for key in CREW_SECRET_KEYS}
