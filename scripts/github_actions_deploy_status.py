#!/usr/bin/env python3
"""Print recent 'Deploy to Droplet' runs + tail of failed job logs (for agents / operators).

Setup once (never commit the token):
  1. GitHub → Settings → Developer settings → Fine-grained PAT
     Repo: parkinglot → Permissions: Actions (Read-only), Metadata (Read).
  2. Save as single line in repo root (gitignored):
       echo 'GITHUB_TOKEN=github_pat_xxx' > .env.github
  3. Or export for one shell:  export GITHUB_TOKEN=github_pat_xxx

Run from repo root:
  python3 scripts/github_actions_deploy_status.py
  python3 scripts/github_actions_deploy_status.py --tail 120

If token is missing, prints instructions only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

OWNER_REPO = os.environ.get("GITHUB_REPOSITORY", "jseadonkey/parkinglot")
API = "https://api.github.com"


def _token() -> str:
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    path = os.path.join(os.path.dirname(__file__), "..", ".env.github")
    path = os.path.normpath(path)
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8").read().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, val = line.split("=", 1)
            if k.strip() in ("GITHUB_TOKEN", "GH_TOKEN"):
                return val.strip().strip('"').strip("'")
    return ""


def _request(url: str, token: str) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        return e.getcode(), e.read()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Deploy to Droplet workflow status from GitHub API")
    parser.add_argument("--tail", type=int, default=80, help="Lines of failed job log to print")
    args = parser.parse_args()

    token = _token()
    if not token:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    owner, repo = OWNER_REPO.split("/", 1)
    url = f"{API}/repos/{owner}/{repo}/actions/runs?per_page=15"
    code, body = _request(url, token)
    if code != 200:
        print(f"GitHub API error {code}: {body[:500]!r}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(body.decode())
    deploy_runs = [r for r in data.get("workflow_runs", []) if r.get("name") == "Deploy to Droplet"]
    if not deploy_runs:
        print("No 'Deploy to Droplet' runs in last page.")
        sys.exit(0)

    print(f"Repository: {OWNER_REPO}\n")
    for r in deploy_runs[:8]:
        print(
            f"- {r['status']:10} {r['conclusion'] or '—':12}  branch={r['head_branch']!r:42}  "
            f"{r['created_at']}  {r['html_url']}"
        )

    latest_fail = next((r for r in deploy_runs if r.get("conclusion") == "failure"), None)
    if not latest_fail:
        print("\n(No failed deploy in recent list; nothing to tail.)")
        sys.exit(0)

    run_id = latest_fail["id"]
    print(f"\n--- Latest failed run {run_id} — job logs (tail {args.tail} lines) ---\n")

    jurl = f"{API}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs"
    code, body = _request(jurl, token)
    if code != 200:
        print(f"Jobs API {code}: {body[:300]!r}", file=sys.stderr)
        sys.exit(1)
    jobs = json.loads(body.decode()).get("jobs", [])
    for job in jobs:
        if job.get("conclusion") != "failure":
            continue
        job_id = job["id"]
        name = job.get("name", job_id)
        log_url = f"{API}/repos/{owner}/{repo}/actions/jobs/{job_id}/logs"
        lc, raw = _request(log_url, token)
        if lc != 200:
            print(f"Job {name}: could not download logs (HTTP {lc})\n")
            continue
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        tail = lines[-args.tail :] if len(lines) > args.tail else lines
        print(f"### {name} (job {job_id})\n")
        print("\n".join(tail))
        print()


if __name__ == "__main__":
    main()
