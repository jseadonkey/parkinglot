#!/usr/bin/env python3
"""Snapshot operator-console pages — same API data the browser loads.

Use this when troubleshooting stalled progress, empty tables, or red error banners
in the operator UI. Safe to run on the Droplet or in Cursor workspace (reads deploy/.env).

  python3 scripts/operator_console_snapshot.py
  python3 scripts/operator_console_snapshot.py --json
  python3 scripts/operator_console_snapshot.py --probe-ui   # HTTPS + bridge via UI_HOST

Exit code: 0 all OK, 1 config/load error, 2 one or more page/API failures or stalls detected.
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _load_env(env_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


@dataclass
class PageResult:
    page: str
    ok: bool
    status: int | None = None
    summary: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


@dataclass
class Snapshot:
    ui_host: str
    public_api_url: str
    pages: list[PageResult] = field(default_factory=list)
    ui_probe: dict[str, Any] = field(default_factory=dict)

    @property
    def issue_count(self) -> int:
        n = sum(len(p.issues) for p in self.pages)
        if self.ui_probe.get("issues"):
            n += len(self.ui_probe["issues"])
        return n

    @property
    def failed_pages(self) -> list[PageResult]:
        return [p for p in self.pages if not p.ok]


def _fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
) -> tuple[int, Any, str | None]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return resp.status, None, "empty response body"
            try:
                return resp.status, json.loads(raw), None
            except json.JSONDecodeError:
                snippet = raw[:120].replace("\n", " ")
                return resp.status, None, f"non-JSON response: {snippet!r}"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return e.code, None, body or str(e)
    except OSError as e:
        return 0, None, str(e)


def _fetch_internal(
    api_base: str,
    path: str,
    internal_key: str,
    *,
    ui_base: str = "",
    prefer_bridge: bool = False,
) -> tuple[int, Any, str | None, str]:
    """Returns (status, data, error, via) where via is 'bridge' or 'api'."""
    if prefer_bridge and ui_base:
        code, data, err = _fetch_json(
            f"{ui_base.rstrip('/')}/operator/api/bridge/{path.lstrip('/')}",
            headers={"X-Internal-Key": internal_key},
        )
        if not err and data is not None:
            return code, data, None, "bridge"
    code, data, err = _fetch_json(
        f"{api_base.rstrip('/')}/{path.lstrip('/')}",
        headers={"X-Internal-Key": internal_key},
    )
    return code, data, err, "api"


def _public_url(api_base: str, path: str) -> tuple[int, Any, str | None]:
    return _fetch_json(f"{api_base.rstrip('/')}/{path.lstrip('/')}")


def _readiness_issues(data: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    zoning_pct = float((data.get("parcels_missing_zoning_code") or {}).get("pct") or 0)
    if zoning_pct > 90:
        issues.append(f"{zoning_pct:.1f}% parcels missing zoning_code (run Phase B)")
    ent_pct = float((data.get("parcels_missing_score_entitlement") or {}).get("pct") or 0)
    if ent_pct > 40:
        issues.append(f"{ent_pct:.1f}% missing entitlement score")
    return issues


def _probe_overview(api: str, key: str, prefer_bridge: bool, ui: str) -> PageResult:
    issues: list[str] = []
    code, data, err, via = _fetch_internal(
        api, "internal/stats/export-readiness", key, ui_base=ui, prefer_bridge=prefer_bridge
    )
    if err or not isinstance(data, dict):
        return PageResult(
            page="overview",
            ok=False,
            status=code or None,
            summary="export-readiness failed",
            issues=[err or f"HTTP {code}"],
        )

    issues.extend(_readiness_issues(data))
    steps = data.get("recommended_next_steps")
    if isinstance(steps, list) and steps:
        issues.append(f"recommended: {steps[0]}")

    code2, summary, err2, via2 = _fetch_internal(
        api, "internal/stats/scoring-summary", key, ui_base=ui, prefer_bridge=prefer_bridge
    )
    r2_summary = "scoring summary unavailable"
    if err2 or not isinstance(summary, dict):
        issues.append(err2 or f"scoring-summary HTTP {code2}")
    else:
        total = summary.get("total_parcels", 0)
        ent = summary.get("parcels_with_latest_entitlement_score", 0)
        qual = summary.get("qualified_count_entitlement", 0)
        r2_summary = f"{total} parcels; {ent} scored; {qual} qualified (via {via2})"
        if total and ent / total < 0.1:
            issues.append(f"Only {ent}/{total} parcels have entitlement scores (<10%)")

    return PageResult(
        page="overview",
        ok=code == 200 and code2 == 200,
        status=code,
        summary=f"{r2_summary} (readiness via {via})",
        detail={
            "export_readiness": {k: data[k] for k in list(data.keys())[:12]},
            "scoring_summary": summary if isinstance(summary, dict) else None,
        },
        issues=issues,
    )


def _probe_parcels(api: str) -> PageResult:
    code, data, err = _public_url(api, "parcels?limit=50")
    if err or not isinstance(data, list):
        return PageResult(page="parcels", ok=False, status=code or None, summary="fetch failed", issues=[err or f"HTTP {code}"])
    missing_zoning = sum(1 for r in data if isinstance(r, dict) and not r.get("zoning_code"))
    issues: list[str] = []
    if data and missing_zoning / len(data) > 0.9:
        issues.append(f"{missing_zoning}/{len(data)} sample rows missing zoning_code (Phase B?)")
    return PageResult(
        page="parcels",
        ok=True,
        status=code,
        summary=f"{len(data)} rows (limit 50)",
        detail={"sample_missing_zoning": missing_zoning},
        issues=issues,
    )


def _probe_deals(api: str, key: str, prefer_bridge: bool, ui: str) -> PageResult:
    code, data, err, via = _fetch_internal(
        api,
        "internal/stats/workflow-failures",
        key,
        ui_base=ui,
        prefer_bridge=prefer_bridge,
    )
    if err or not isinstance(data, dict):
        return PageResult(page="deals", ok=False, status=code or None, summary="fetch failed", issues=[err or f"HTTP {code}"])

    failed_count = int(data.get("failed_count") or 0)
    blocked_count = int(data.get("blocked_count") or 0)
    groups = data.get("failure_groups") if isinstance(data.get("failure_groups"), list) else []
    by_step = data.get("failed_by_step") if isinstance(data.get("failed_by_step"), dict) else {}
    storage = data.get("storage") if isinstance(data.get("storage"), dict) else {}

    issues: list[str] = []
    if failed_count:
        issues.append(f"{failed_count} failed workflow run(s) in DB (UI shows max 200)")
    if storage and not storage.get("reachable"):
        hint = storage.get("fix_hint") or storage.get("error") or "Storage not reachable"
        issues.append(f"Storage: {hint}")

    enrich_failures = sum(
        int(g.get("count") or 0)
        for g in groups
        if isinstance(g, dict) and g.get("current_step") == "enrich"
    )
    if enrich_failures:
        issues.append(f"{enrich_failures} failed at step enrich (contract draft → Spaces)")

    return PageResult(
        page="deals",
        ok=failed_count == 0 and (not storage or storage.get("reachable", True)),
        status=code,
        summary=f"failed={failed_count}, blocked={blocked_count} (via {via})",
        detail={
            "failed_by_step": by_step,
            "failure_groups": groups[:12],
            "storage": {
                "bucket": storage.get("bucket"),
                "reachable": storage.get("reachable"),
                "error": storage.get("error"),
                "fix_hint": storage.get("fix_hint"),
            },
        },
        issues=issues,
    )


def _probe_approvals(api: str) -> PageResult:
    code, pending, err = _public_url(api, "approvals?status=pending")
    if err or not isinstance(pending, list):
        return PageResult(page="approvals", ok=False, status=code or None, summary="fetch failed", issues=[err or f"HTTP {code}"])
    issues: list[str] = []
    if len(pending) > 200:
        issues.append(f"{len(pending)} pending (UI list cap is 200 — backlog may look truncated)")
    return PageResult(
        page="approvals",
        ok=True,
        status=code,
        summary=f"{len(pending)} pending",
        detail={"pending_count": len(pending)},
        issues=issues,
    )


def _probe_audit(api: str) -> PageResult:
    code, data, err = _public_url(api, "audit?limit=300")
    if err or not isinstance(data, list):
        return PageResult(page="audit", ok=False, status=code or None, summary="fetch failed", issues=[err or f"HTTP {code}"])
    return PageResult(page="audit", ok=True, status=code, summary=f"{len(data)} recent rows", detail={"row_count": len(data)})


def _probe_owners(api: str, key: str, prefer_bridge: bool, ui: str) -> PageResult:
    code, data, err, via = _fetch_internal(
        api,
        "internal/owners/portfolios-ranked?min_peers=2&limit=40",
        key,
        ui_base=ui,
        prefer_bridge=prefer_bridge,
    )
    if err:
        return PageResult(page="owners", ok=False, status=code or None, summary="fetch failed", issues=[err])
    count = 0
    if isinstance(data, dict):
        count = int(data.get("portfolio_count") or len(data.get("portfolios") or []))
    return PageResult(
        page="owners",
        ok=code == 200,
        status=code,
        summary=f"{count} portfolios (via {via})",
        detail={"keys": list(data.keys())[:8] if isinstance(data, dict) else []},
    )


def _probe_outreach(api: str, key: str, prefer_bridge: bool, ui: str) -> PageResult:
    code, data, err, via = _fetch_internal(
        api,
        "internal/pipeline/outreach-board?limit=500",
        key,
        ui_base=ui,
        prefer_bridge=prefer_bridge,
    )
    if err or not isinstance(data, dict):
        return PageResult(page="outreach", ok=False, status=code or None, summary="fetch failed", issues=[err or f"HTTP {code}"])
    rows = data.get("rows") if isinstance(data.get("rows"), list) else []
    stalled = [
        r
        for r in rows
        if isinstance(r, dict)
        and (r.get("workflow_error") or r.get("workflow_status") in ("failed", "error"))
    ]
    issues = [f"{len(stalled)} pipeline row(s) with workflow errors"] if stalled else []
    by_stage: dict[str, int] = {}
    for r in rows:
        if isinstance(r, dict):
            st = str(r.get("pipeline_stage") or "unknown")
            by_stage[st] = by_stage.get(st, 0) + 1
    return PageResult(
        page="outreach",
        ok=code == 200 and not stalled,
        status=code,
        summary=f"{data.get('row_count', len(rows))} qualified rows (via {via})",
        detail={"by_stage": by_stage, "stalled_sample": stalled[:8]},
        issues=issues,
    )


def _probe_ui_shell(ui_host: str, internal_key: str) -> dict[str, Any]:
    """HTTPS checks: operator HTML shell + bridge auth path (X-Internal-Key)."""
    base = f"https://{ui_host.strip()}"
    out: dict[str, Any] = {"ui_base": base, "checks": [], "issues": []}

    def _head_get(path: str, headers: dict[str, str] | None = None) -> tuple[int, str]:
        url = f"{base}{path}"
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=20, context=_ssl_ctx()) as resp:
                body = resp.read(800).decode("utf-8", errors="replace")
                return resp.status, body
        except urllib.error.HTTPError as e:
            body = e.read(800).decode("utf-8", errors="replace")
            return e.code, body
        except OSError as e:
            return 0, str(e)

    code, body = _head_get("/operator")
    login_redirect = code in (301, 302, 307, 308) or "/login" in body
    out["checks"].append({"path": "/operator", "status": code, "login_redirect_or_page": login_redirect})
    if code not in (200, 301, 302, 307, 308):
        out["issues"].append(f"/operator returned HTTP {code}")

    code_b, data_b, err_b = _fetch_json(
        f"{base}/operator/api/bridge/internal/stats/scoring-summary",
        headers={"X-Internal-Key": internal_key, "Accept": "application/json"},
    )
    bridge_ok = code_b == 200 and not err_b and isinstance(data_b, dict)
    out["checks"].append(
        {"path": "/operator/api/bridge/.../scoring-summary", "status": code_b, "json_ok": bridge_ok}
    )
    if not bridge_ok:
        out["issues"].append(
            err_b
            or f"Bridge route HTTP {code_b} — rebuild operator-console after middleware update, or check INTERNAL_API_KEY"
        )
    out["auth"] = {"bridge_key_probe": bridge_ok, "note": "UI login cookie not tested; snapshot uses API + optional bridge"}
    return out


def build_snapshot(env: dict[str, str], *, probe_ui: bool) -> Snapshot:
    api = env.get("PUBLIC_API_URL", "").strip()
    key = env.get("INTERNAL_API_KEY", "").strip()
    ui = env.get("UI_HOST", "").strip()
    if not api:
        raise ValueError("PUBLIC_API_URL missing in deploy/.env")
    if not key:
        raise ValueError("INTERNAL_API_KEY missing in deploy/.env")

    prefer_bridge = probe_ui and bool(ui)
    ui_base = f"https://{ui}" if ui else ""

    snap = Snapshot(ui_host=ui, public_api_url=api)
    snap.pages = [
        _probe_overview(api, key, prefer_bridge, ui_base),
        _probe_parcels(api),
        _probe_deals(api, key, prefer_bridge, ui_base),
        _probe_approvals(api),
        _probe_audit(api),
        _probe_owners(api, key, prefer_bridge, ui_base),
        _probe_outreach(api, key, prefer_bridge, ui_base),
    ]
    if probe_ui and ui:
        snap.ui_probe = _probe_ui_shell(ui, key)
    return snap


def _print_human(snap: Snapshot) -> None:
    print(f"Operator console snapshot")
    print(f"  UI_HOST={snap.ui_host or '(unset)'}")
    print(f"  PUBLIC_API_URL={snap.public_api_url}")
    print()
    for p in snap.pages:
        flag = "OK" if p.ok and not p.issues else "WARN" if p.ok else "FAIL"
        print(f"[{flag}] {p.page}: {p.summary}")
        for issue in p.issues:
            print(f"       ! {issue}")
        if p.detail.get("failure_groups"):
            for g in p.detail["failure_groups"][:5]:
                if isinstance(g, dict):
                    print(
                        f"       · {g.get('current_step')} ×{g.get('count')}: {g.get('error_signature')}"
                    )
                    parcels = g.get("sample_parcel_ids") or []
                    if parcels:
                        print(f"         parcels: {', '.join(str(x)[:8] + '…' for x in parcels[:4])}")
        if p.detail.get("storage") and isinstance(p.detail["storage"], dict):
            st = p.detail["storage"]
            if st.get("error"):
                print(f"       · bucket {st.get('bucket')}: {st.get('error')}")
        if p.detail.get("stalled_sample"):
            for s in p.detail["stalled_sample"][:3]:
                if isinstance(s, dict):
                    print(f"       · parcel {s.get('apn')} stage={s.get('pipeline_stage')} err={s.get('workflow_error')}")
    if snap.ui_probe:
        print()
        print("=== UI / bridge (HTTPS) ===")
        for c in snap.ui_probe.get("checks", []):
            print(f"  {c.get('path')}: HTTP {c.get('status')}")
        for issue in snap.ui_probe.get("issues", []):
            print(f"  ! {issue}")
    print()
    if snap.issue_count:
        print(f"Snapshot: {snap.issue_count} issue(s) — see WARN/FAIL above.")
    else:
        print("Snapshot: all operator pages reachable; no stalled workflows detected.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Snapshot operator-console page data for troubleshooting.")
    ap.add_argument("repo", nargs="?", default=".", help="Repo root (default: cwd)")
    ap.add_argument("--json", action="store_true", help="Print JSON (for agents)")
    ap.add_argument(
        "--probe-ui",
        action="store_true",
        help="Also probe https://UI_HOST/operator and bridge routes (TLS verify off)",
    )
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    env_path = repo / "deploy" / ".env"
    if not env_path.is_file():
        print(f"Missing {env_path} — run: python3 scripts/render_deploy_env.py", file=sys.stderr)
        return 1

    try:
        snap = build_snapshot(_load_env(env_path), probe_ui=args.probe_ui)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    if args.json:
        payload = {
            "ui_host": snap.ui_host,
            "public_api_url": snap.public_api_url,
            "pages": [asdict(p) for p in snap.pages],
            "ui_probe": snap.ui_probe,
            "issue_count": snap.issue_count,
        }
        print(json.dumps(payload, indent=2))
    else:
        _print_human(snap)

    if snap.failed_pages or snap.issue_count:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
