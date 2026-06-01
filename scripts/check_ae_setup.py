#!/usr/bin/env python3
"""Check A–E–related keys in deploy/.env (read-only). Optional HTTPS /ready probe.

  cd /opt/workspaces/parkinglot
  python3 scripts/check_ae_setup.py
  python3 scripts/check_ae_setup.py /opt/workspaces/parkinglot
  python3 scripts/check_ae_setup.py --probe
"""
from __future__ import annotations

import argparse
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
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


def _ok(has: bool) -> str:
    return "OK " if has else "MISSING"


def _probe_ready(url: str) -> tuple[bool, str]:
    """GET {base}/ready — tolerate self-signed TLS (internal Caddy)."""
    base = url.rstrip("/")
    probe_url = f"{base}/ready"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(probe_url, timeout=15, context=ctx) as resp:
            code = resp.getcode()
            return code == 200, f"{probe_url} -> HTTP {code}"
    except urllib.error.HTTPError as e:
        return False, f"{probe_url} -> HTTP {e.code}"
    except OSError as e:
        return False, f"{probe_url} -> {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify deploy/.env for phased A–E operations.")
    ap.add_argument(
        "repo",
        nargs="?",
        default=".",
        help="Repo root (default: cwd)",
    )
    ap.add_argument(
        "--probe",
        action="store_true",
        help="GET PUBLIC_API_URL/ready (skips TLS verify for internal certs)",
    )
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    env_path = repo / "deploy" / ".env"
    if not env_path.is_file():
        print(f"Missing {env_path}", file=sys.stderr)
        return 1

    env = _load_env_lines(env_path)
    errors = 0

    print("=== Shared (deploy + Celery + storage) ===")
    shared_required = [
        "DATABASE_URL",
        "REDIS_URL",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
        "PUBLIC_API_URL",
    ]
    for k in shared_required:
        v = env.get(k, "")
        good = bool(v) and "changeme" not in v.lower()
        print(f"  {_ok(good)} {k}")
        if not good:
            errors += 1

    # INTERNAL_API_KEY strongly recommended when API enforces internal routes
    ikey = env.get("INTERNAL_API_KEY", "")
    ik_ok = bool(ikey) and len(ikey) >= 16
    print(f"  {_ok(ik_ok)} INTERNAL_API_KEY (recommended for /internal/*)")
    if not ik_ok:
        errors += 1

    storage_ok = bool(env.get("STORAGE_ENDPOINT")) and bool(env.get("STORAGE_BUCKET"))
    print(f"  {_ok(storage_ok)} STORAGE_* (endpoint + bucket — contract drafts / uploads)")
    if not storage_ok:
        print("       WARN: pipelines may fail at contract draft without object storage.")

    print()
    print("=== Phase A — scheduling & pilot ===")
    enq = env.get("SCHEDULED_ENQUEUE_UNSCORED_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    enq_val = env.get("SCHEDULED_ENQUEUE_UNSCORED_ENABLED", "true")
    print(f"  {'OK ' if enq else 'OFF '} SCHEDULED_ENQUEUE_UNSCORED_ENABLED={enq_val}")
    rid = env.get("SCHEDULED_REFRESH_IDENTIFICATION_ENABLED", "").lower() in ("1", "true", "yes", "on")
    rdd = env.get("SCHEDULED_REFRESH_DEMAND_ENABLED", "").lower() in ("1", "true", "yes", "on")
    print(f"  {'ON ' if rid else 'OFF '} SCHEDULED_REFRESH_IDENTIFICATION_ENABLED (optional Beat)")
    print(f"  {'ON ' if rdd else 'OFF '} SCHEDULED_REFRESH_DEMAND_ENABLED (optional Beat)")
    print("  INFO pilot.yaml demand_generators — edit file under config/ (not only .env)")

    print()
    print("=== Phase B — zoning overlay ===")
    zr = env.get("ZONING_RULES_PATH", "").strip()
    print(f"  INFO ZONING_RULES_PATH={'set' if zr else 'default bundled rules under data/zoning/wa/'}")
    print("  INFO Overlay GeoJSON — you stage under data/ → /app/data/... then execute-phase-b.sh")

    print()
    print("=== Phase C — optional vendor ===")
    ven = env.get("OWNER_VENDOR_LOOKUP_ENABLED", "").lower() in ("1", "true", "yes", "on")
    if ven:
        vurl = bool(env.get("OWNER_VENDOR_LOOKUP_URL", "").strip())
        vkey = bool(env.get("OWNER_VENDOR_LOOKUP_API_KEY", "").strip())
        print(f"  {'OK ' if vurl and vkey else 'BAD '} OWNER_VENDOR_LOOKUP_* (enabled)")
        if not (vurl and vkey):
            errors += 1
    else:
        print("  OFF OWNER_VENDOR_LOOKUP_ENABLED (optional)")

    print()
    print("=== Phase D / E ===")
    print("  INFO Phase D — GIS inputs for corner/rich demand when you add data.")
    print("  INFO Phase E — expand region.county_fips in config/pilot.yaml + ingest per county.")

    print()
    wr_py = repo / "scripts" / "check_deploy_env_warnings.py"
    if wr_py.is_file():
        print("=== Placeholder / TLS hint (check_deploy_env_warnings) ===")
        r = subprocess.run(
            [sys.executable, str(wr_py), str(repo)],
            capture_output=True,
            text=True,
        )
        sys.stdout.write(r.stdout)
        if r.stderr:
            sys.stderr.write(r.stderr)
        if r.returncode != 0:
            errors += 1

    if args.probe:
        print()
        pub = env.get("PUBLIC_API_URL", "").strip()
        if not pub:
            print("=== /ready probe skipped (PUBLIC_API_URL empty) ===")
            errors += 1
        else:
            print("=== GET /ready (TLS verify off) ===")
            ok, msg = _probe_ready(pub)
            print(f"  {'OK ' if ok else 'FAIL'} {msg}")
            if not ok:
                errors += 1

    print()
    if errors:
        print(f"check_ae_setup: {errors} issue(s) — fix deploy/.env or infra.")
        return 2
    print("check_ae_setup: core keys look usable for phased ops.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
