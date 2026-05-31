"""Slow, browser-based WA Secretary of State (CCFS) entity lookup.

The public CCFS API (``ccfs-api.prod.sos.wa.gov``) requires a Cloudflare Turnstile
token on each call. We obtain that token by loading the official CCFS SPA in
Playwright and issuing ``fetch`` from the page context — the same path a human
browser uses. Requests are serialized with a configurable minimum delay.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

_CCFS_HOME = "https://ccfs.sos.wa.gov/#/BusinessSearch"
_API_BASE = "https://ccfs-api.prod.sos.wa.gov/api"

_LOOKUP_JS = """
async ({ entityName }) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const getToken = () => {
    try {
      return angular.element(document.body).injector().get("$rootScope").reCaptcha;
    } catch (e) {
      return null;
    }
  };
  const waitToken = async () => {
    for (let i = 0; i < 120; i++) {
      const t = getToken();
      if (t) return t;
      await sleep(500);
    }
    return null;
  };
  const post = async (path, dataObj, token) => {
    const body = new URLSearchParams(dataObj).toString();
    const r = await fetch(`${API_BASE}/${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-reCAPTCHA": token,
      },
      body,
    });
    return r.json();
  };
  const get = async (path, params, token) => {
    const qs = new URLSearchParams(params).toString();
    const r = await fetch(`${API_BASE}/${path}?${qs}`, {
      headers: { "X-reCAPTCHA": token },
    });
    return r.json();
  };
  const API_BASE = "https://ccfs-api.prod.sos.wa.gov/api";
  const token = await waitToken();
  if (!token) return { error: "turnstile_token_timeout" };
  const search = await post(
    "BusinessSearch/GetBusinessSearchList",
    {
      Type: "BusinessName",
      SearchType: "Contains",
      SearchEntityName: entityName,
      SearchValue: entityName,
      SearchCriteria: entityName,
      IsSearch: "true",
      PageID: "1",
      PageCount: "25",
    },
    token,
  );
  if (typeof search === "string") return { error: search };
  const list = Array.isArray(search) ? search : Object.values(search || {});
  if (!list.length) return { error: "no_results", raw_result_count: 0 };
  const norm = (s) => (s || "").toUpperCase().replace(/[^A-Z0-9 ]+/g, " ").replace(/\\s+/g, " ").trim();
  const target = norm(entityName);
  let hit =
    list.find((x) => norm(x.BusinessName) === target) ||
    list.find((x) => norm(x.BusinessName).includes(target) || target.includes(norm(x.BusinessName))) ||
    list[0];
  if (!hit || !hit.BusinessID) return { error: "no_match", raw_result_count: list.length };
  const detail = await get("BusinessSearch/BusinessInformation", { businessID: String(hit.BusinessID) }, token);
  if (typeof detail === "string") return { error: detail, raw_result_count: list.length };
  const agent = detail.Agent || {};
  const agentName =
    [agent.FirstName, agent.LastName].filter(Boolean).join(" ").trim() ||
    agent.OrganizationName ||
    agent.EntityName ||
    hit.AgentName ||
    null;
  const agentAddr =
    (agent.StreetAddress && agent.StreetAddress.FullAddress) ||
    (hit.AgentAddress && hit.AgentAddress.FullAddress) ||
    null;
  const principals = (detail.PrincipalsList || []).map((p) => ({
    name: p.FullName || p.Name || null,
    role: p.PrincipalBaseType || p.Title || null,
    address:
      (p.PrincipalMailingAddress && p.PrincipalMailingAddress.FullAddress) ||
      (p.PrincipalStreetAddress && p.PrincipalStreetAddress.FullAddress) ||
      null,
  }));
  const principalAddr =
    (detail.PrincipalOffice &&
      detail.PrincipalOffice.PrincipalStreetAddress &&
      detail.PrincipalOffice.PrincipalStreetAddress.FullAddress) ||
    (detail.PrincipalOffice &&
      detail.PrincipalOffice.PrincipalMailingAddress &&
      detail.PrincipalOffice.PrincipalMailingAddress.FullAddress) ||
    null;
  return {
    raw_result_count: list.length,
    business_id: hit.BusinessID,
    business_name: detail.BusinessName || hit.BusinessName,
    ubi: detail.UBINumber || hit.UBINumber || null,
    status: detail.BusinessStatus || hit.BusinessStatus || null,
    agent_name: agentName,
    agent_address: agentAddr,
    principal_address: principalAddr,
    principals,
  };
}
"""


def wa_ccfs_search_url_for_manual_review(entity_name: str) -> str:
    q = quote_plus(entity_name.strip())
    return f"https://ccfs.sos.wa.gov/#/BusinessSearch?SearchCriteria={q}"


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 ]+", " ", name.upper())).strip()


@dataclass
class WaSosLookupResult:
    outcome: str
    query_used: str
    raw_result_count: int = 0
    top_match_name: str | None = None
    top_match_ubi: str | None = None
    registered_agent_line: str | None = None
    registered_agent_address: str | None = None
    principal_address_line: str | None = None
    principals: list[dict[str, str | None]] | None = None
    detail_url: str | None = None
    error_detail: str | None = None
    notes: str | None = None


def lookup_wa_entity_via_ccfs(
    entity_name: str,
    *,
    min_delay_s: float = 60.0,
    last_lookup_at: float | None = None,
) -> WaSosLookupResult:
    """Look up one WA entity on CCFS using Playwright + in-page fetch."""
    query = (entity_name or "").strip()
    if not query:
        return WaSosLookupResult(outcome="error", query_used=query, error_detail="empty entity name")

    if last_lookup_at is not None:
        wait = min_delay_s - (time.monotonic() - last_lookup_at)
        if wait > 0:
            time.sleep(wait)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return WaSosLookupResult(
            outcome="error",
            query_used=query,
            error_detail="playwright not installed",
            notes="Install playwright + chromium for automated WA SOS lookup.",
        )

    try:
        with sync_playwright() as p:
            # Headed Chromium under xvfb passes Turnstile more reliably than headless shell.
            use_headed = True
            try:
                browser = p.chromium.launch(
                    headless=not use_headed,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
            except Exception:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            try:
                page = browser.new_page(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 900},
                )
                page.goto(_CCFS_HOME, wait_until="domcontentloaded", timeout=90000)
                # Give Turnstile time to render and auto-verify in a real browser context.
                try:
                    page.locator("iframe[src*='challenges.cloudflare']").first.click(timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(8000)
                raw: dict[str, Any] = page.evaluate(_LOOKUP_JS, {"entityName": query})
            finally:
                browser.close()
    except Exception as exc:
        return WaSosLookupResult(
            outcome="error",
            query_used=query,
            error_detail=str(exc)[:2000],
            notes="WA SOS browser lookup failed — retry later or use manual CCFS link.",
        )

    if not isinstance(raw, dict):
        return WaSosLookupResult(
            outcome="error",
            query_used=query,
            error_detail=f"unexpected response type: {type(raw).__name__}",
        )

    err = raw.get("error")
    if err:
        if err in ("no_results", "no_match"):
            return WaSosLookupResult(
                outcome="no_results",
                query_used=query,
                raw_result_count=int(raw.get("raw_result_count") or 0),
                detail_url=wa_ccfs_search_url_for_manual_review(query),
                notes=f"CCFS search returned no confident match ({err}).",
            )
        return WaSosLookupResult(
            outcome="error",
            query_used=query,
            error_detail=str(err)[:2000],
            detail_url=wa_ccfs_search_url_for_manual_review(query),
        )

    business_id = raw.get("business_id")
    detail_url = (
        f"https://ccfs.sos.wa.gov/#/BusinessInformation?businessId={business_id}"
        if business_id
        else wa_ccfs_search_url_for_manual_review(query)
    )
    principals = raw.get("principals") or []
    agent = raw.get("agent_name")
    agent_addr = raw.get("agent_address")
    principal_addr = raw.get("principal_address")

    if not agent and not principals and not principal_addr:
        return WaSosLookupResult(
            outcome="no_results",
            query_used=query,
            raw_result_count=int(raw.get("raw_result_count") or 0),
            top_match_name=raw.get("business_name"),
            top_match_ubi=raw.get("ubi"),
            detail_url=detail_url,
            notes="Entity found on CCFS but no agent/principal rows returned.",
        )

    return WaSosLookupResult(
        outcome="hit",
        query_used=query,
        raw_result_count=int(raw.get("raw_result_count") or 0),
        top_match_name=raw.get("business_name"),
        top_match_ubi=raw.get("ubi"),
        registered_agent_line=agent,
        registered_agent_address=agent_addr,
        principal_address_line=principal_addr,
        principals=principals,
        detail_url=detail_url,
        notes="Automated CCFS lookup — verify on SOS before outreach.",
    )
