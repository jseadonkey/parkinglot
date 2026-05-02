#!/usr/bin/env python3
"""Run on the Droplet after editing deploy/.env — warns about placeholder URLs / hosts.

  cd /opt/workspaces/parkinglot
  python3 scripts/check_deploy_env_warnings.py
  python3 scripts/check_deploy_env_warnings.py /opt/workspaces/parkinglot
"""
from __future__ import annotations

import sys
from pathlib import Path


def _load_env_lines(env_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> int:
    repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    env_path = repo / "deploy" / ".env"
    if not env_path.is_file():
        print(f"Missing {env_path}", file=sys.stderr)
        return 1

    env = _load_env_lines(env_path)
    warnings: list[str] = []

    du = env.get("DATABASE_URL", "")
    if du and "@postgres:" in du:
        warnings.append(
            "DATABASE_URL still points at host 'postgres' (Docker-only). "
            "Use your DigitalOcean managed DB hostname instead.",
        )

    for key in ("PUBLIC_API_URL",):
        v = env.get(key, "")
        if not v:
            warnings.append(f"{key} is empty.")
            continue
        if "example.com" in v or "parking.example.com" in v:
            warnings.append(
                f"{key} looks like a placeholder ({v}). "
                "Set it to your real API URL (same host Caddy uses for TLS).",
            )

    for key in ("API_HOST", "UI_HOST"):
        v = env.get(key, "")
        if v and ("example.com" in v or v.startswith("YOUR_")):
            warnings.append(f"{key} may still be a placeholder: {v}")

    acme = env.get("ACME_EMAIL", "")
    if acme and ("example.com" in acme or acme.strip() == "you@yourdomain.com"):
        warnings.append("ACME_EMAIL may still be the template — set a real email for Let's Encrypt.")

    if warnings:
        print("Warnings (fix before relying on public HTTPS):\n")
        for w in warnings:
            print(f"  - {w}")
        print("\nSee docs/GO-LIVE-WASHINGTON-DO.md and deploy/env.production.example.")
        return 2

    print("No placeholder warnings for DATABASE_URL / PUBLIC_API_URL / hosts / ACME_EMAIL.")
    print("(DNS must still resolve from the internet — test with curl from your laptop.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
