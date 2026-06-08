#!/usr/bin/env python3
"""Prune duplicate pending approvals on the API (keeps newest per parcel+type).

Usage:
  API_URL=https://api.vspecialist.com python3 scripts/prune-pending-approvals.py
  API_URL=https://api.vspecialist.com python3 scripts/prune-pending-approvals.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Any


def _get(url: str) -> list[dict[str, Any]]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status >= 400:
                raise urllib.error.HTTPError(url, resp.status, resp.reason, resp.headers, resp.read())
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{url} -> HTTP {exc.code}: {detail[:200]}") from exc


def _plan(pending: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in pending:
        payload = row.get("payload") or {}
        parcel_id = str(payload.get("parcel_id") or "")
        groups[(row["type"], parcel_id)].append(row)

    approve: list[str] = []
    reject: list[str] = []
    for key in sorted(groups):
        approval_type, _parcel_id = key
        rows = groups[key]
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        keep, dupes = rows[0], rows[1:]
        if approval_type == "deal_memo_publish":
            approve.append(keep["id"])
            reject.extend(r["id"] for r in dupes)
        elif approval_type == "contract_send":
            reject.extend(r["id"] for r in dupes)
        else:
            reject.extend(r["id"] for r in dupes)
    return approve, reject


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune duplicate pending approvals")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="POST approve/reject actions (default is dry-run)",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("API_URL", "https://api.vspecialist.com"),
        help="API base URL",
    )
    parser.add_argument(
        "--actor",
        default=os.environ.get("APPROVAL_ACTOR", "cursor-agent"),
        help="approved_by value for API decisions",
    )
    args = parser.parse_args()
    base = args.api_url.rstrip("/")

    try:
        pending = _get(f"{base}/approvals?status=pending&limit=2000")
    except urllib.error.URLError as exc:
        print(f"FAIL: could not fetch pending approvals: {exc}", file=sys.stderr)
        return 1

    approve, reject = _plan(pending)
    print(f"Pending total: {len(pending)}")
    print(f"Plan: approve {len(approve)} deal memos, reject {len(reject)} duplicates")

    if not args.apply:
        print("Dry run — pass --apply to execute.")
        return 0

    round_num = 0
    while True:
        round_num += 1
        acted = 0
        for approval_id in approve:
            try:
                _post(
                    f"{base}/approvals/{approval_id}/approve",
                    {"approved_by": args.actor, "note": "auto-approved (pilot deal memo)"},
                )
                acted += 1
            except RuntimeError as exc:
                if "approval is not pending" not in str(exc):
                    print(f"WARN approve {approval_id}: {exc}", file=sys.stderr)

        for approval_id in reject:
            try:
                _post(
                    f"{base}/approvals/{approval_id}/reject",
                    {"approved_by": args.actor, "note": "duplicate pruned"},
                )
                acted += 1
            except RuntimeError as exc:
                if "approval is not pending" not in str(exc):
                    print(f"WARN reject {approval_id}: {exc}", file=sys.stderr)

        remaining = _get(f"{base}/approvals?status=pending&limit=2000")
        print(f"Round {round_num}: acted={acted}, pending={len(remaining)}")
        if len(remaining) <= 10 or acted == 0:
            print(f"Done. Pending remaining: {len(remaining)}")
            break
        pending = remaining
        approve, reject = _plan(pending)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
