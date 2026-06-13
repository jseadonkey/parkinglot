import { expect, test, type Page, type Response } from "@playwright/test";
import { writeFileSync } from "node:fs";
import {
  countTableDataRows,
  countVisibleZeroGrabRows,
  expandOverviewCounties,
  scrollFullPage,
  tryClickRefresh,
} from "../lib/pageLoad";
import { buildScrapeCoverage, type CountyZeroGrab } from "../lib/scrapeCoverage";

type PageSpec = {
  path: string;
  label: string;
  mustInclude?: string;
  settleMs?: number;
  /** Extra actions after first settle (overview county table, etc.). */
  afterLoad?: (page: Page) => Promise<void>;
};

/** Every operator-console nav route from lib/siteNav.ts (mounted under /operator). */
const OPERATOR_PAGES: PageSpec[] = [
  { path: "/operator", label: "Overview", mustInclude: "Overview", settleMs: 60_000, afterLoad: expandOverviewCounties },
  { path: "/operator/outreach", label: "Outreach pipeline", mustInclude: "Outreach pipeline", settleMs: 45_000 },
  { path: "/operator/approvals", label: "Approvals", mustInclude: "Approvals", settleMs: 30_000 },
  { path: "/operator/backlog", label: "Backlog ETA", mustInclude: "Backlog ETA", settleMs: 30_000 },
  { path: "/operator/deals", label: "Deal progress", mustInclude: "Deal progress", settleMs: 60_000 },
  { path: "/operator/parcels", label: "Parcels", mustInclude: "Parcels", settleMs: 120_000 },
  { path: "/operator/owners", label: "Portfolios", mustInclude: "Portfolios", settleMs: 45_000 },
  { path: "/operator/templates", label: "Message templates", mustInclude: "Message templates", settleMs: 30_000 },
  { path: "/operator/audit", label: "Audit log", mustInclude: "Audit log", settleMs: 30_000 },
  {
    path: "/operator/platform",
    label: "Platform showcase",
    mustInclude: "County GIS ingest",
    settleMs: 60_000,
  },
];

type ApiFailure = { status: number; url: string; page: string };
type PageIssue = { page: string; label: string; detail: string; severity?: "error" | "warning" };
type PageAnalysis = {
  table_rows: number;
  zero_grab_rows_visible: number;
  fully_loaded: boolean;
  scrolled: boolean;
  refreshed: boolean;
};
type PageResult = {
  path: string;
  label: string;
  ok: boolean;
  load_ms: number;
  issues: PageIssue[];
  analysis: PageAnalysis;
};

type BacklogMetrics = Record<string, number>;

function attachApiTracker(page: Page, getLabel: () => string, sink: ApiFailure[]) {
  page.on("response", (res: Response) => {
    const url = res.url();
    if (!url.includes("/operator/api/bridge/")) return;
    if (res.status() >= 400) {
      sink.push({ status: res.status(), url, page: getLabel() });
    }
  });
}

async function loginAsAdmin(page: Page) {
  const email = process.env.UI_SMOKE_ADMIN_EMAIL?.trim();
  const password = process.env.UI_SMOKE_ADMIN_PASSWORD ?? "";
  if (!email || !password) {
    test.skip(true, "Set UI_SMOKE_ADMIN_EMAIL and UI_SMOKE_ADMIN_PASSWORD");
  }

  await page.goto("/login");
  await page.getByLabel("Email or username").fill(email!);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 30_000 });
}

async function waitForPageSettled(page: Page, maxMs: number) {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    const text = await page.locator("body").innerText();
    const loading =
      /Loading(…|\.{3})/.test(text) ||
      text.includes("Loading readiness") ||
      text.includes("Loading backlog") ||
      text.includes("Loading parcels") ||
      text.includes("Loading portfolios") ||
      text.includes("Loading template") ||
      text.includes("Loading funnel") ||
      text.includes("Loading scoring") ||
      text.includes("Loading parcel counts");
    if (!loading) return;
    await page.waitForTimeout(2_000);
  }
}

async function fetchBridgeJson(page: Page, bridgePath: string): Promise<unknown | null> {
  return page.evaluate(async (path) => {
    const res = await fetch(`/operator/api/bridge/${path}`, { credentials: "include" });
    if (!res.ok) return { __error: res.status, __path: path };
    return res.json();
  }, bridgePath);
}

function backlogCounts(raw: unknown): BacklogMetrics {
  if (!raw || typeof raw !== "object") return {};
  const items = (raw as { items?: unknown }).items;
  if (!Array.isArray(items)) return {};
  const out: BacklogMetrics = {};
  for (const it of items) {
    if (it && typeof it === "object" && "key" in it && "backlog_count" in it) {
      out[String((it as { key: string }).key)] = Number((it as { backlog_count: number }).backlog_count) || 0;
    }
  }
  return out;
}

function scrapeGapWarnings(gaps: CountyZeroGrab[]): PageIssue[] {
  const issues: PageIssue[] = [];
  for (const g of gaps) {
    if (g.kind === "pilot_priority") {
      issues.push({
        page: "/operator",
        label: "Scrape coverage",
        severity: "warning",
        detail: `Priority county ${g.county_name} (${g.county_fips}) has 0 parcels ingested`,
      });
    } else if (g.kind === "wa_rollout_next") {
      issues.push({
        page: "/operator",
        label: "Scrape coverage",
        severity: "warning",
        detail: `Next WA rollout county ${g.county_name} (${g.county_fips}) has 0 parcels — ingest not started`,
      });
    }
  }
  return issues;
}

test.describe("Operator admin agent", () => {
  test("daily scan — all pages, metrics, regressions", async ({ page }) => {
    const apiFailures: ApiFailure[] = [];
    const pageResults: PageResult[] = [];
    let currentLabel = "login";
    attachApiTracker(page, () => currentLabel, apiFailures);

    await loginAsAdmin(page);

    const parcelList = (await fetchBridgeJson(
      page,
      "internal/parcels/scored-list?limit=1&qualified_only=true",
    )) as { rows?: { parcel_id?: string }[] } | null;
    const sampleParcelId = parcelList?.rows?.[0]?.parcel_id ?? null;

    const pagesToVisit = [...OPERATOR_PAGES];
    if (sampleParcelId) {
      pagesToVisit.push({
        path: `/operator/parcels/${sampleParcelId}`,
        label: "Parcel detail",
        mustInclude: sampleParcelId.slice(0, 8),
        settleMs: 45_000,
      });
    }

    for (const entry of pagesToVisit) {
      currentLabel = entry.label;
      const issues: PageIssue[] = [];
      const beforeApi = apiFailures.length;
      const started = Date.now();
      let refreshed = false;

      const response = await page.goto(entry.path, { waitUntil: "domcontentloaded" });
      await waitForPageSettled(page, entry.settleMs ?? 45_000);

      const bodyBeforeRefresh = await page.locator("body").innerText();
      if (/Loading(…|\.{3})/.test(bodyBeforeRefresh)) {
        await tryClickRefresh(page);
        refreshed = true;
        await waitForPageSettled(page, Math.min(entry.settleMs ?? 45_000, 60_000));
      }

      if (entry.afterLoad) {
        await entry.afterLoad(page);
        await page.waitForTimeout(800);
      }

      await scrollFullPage(page);
      await waitForPageSettled(page, 8_000);

      const status = response?.status() ?? 0;
      if (status >= 400) {
        issues.push({ page: entry.path, label: entry.label, detail: `HTTP ${status} on navigation` });
      }

      const title = await page.title();
      if (/404|not found/i.test(title)) {
        issues.push({ page: entry.path, label: entry.label, detail: `Page title: ${title}` });
      }

      const bodyText = (await page.locator("body").innerText()).slice(0, 16_000);
      for (const pattern of [
        /HTTP 503/i,
        /HTTP 502/i,
        /HTTP 404/i,
        /INTERNAL_API_KEY not configured/i,
        /NoSuchBucket/i,
      ]) {
        if (pattern.test(bodyText)) {
          issues.push({
            page: entry.path,
            label: entry.label,
            detail: `Visible error matched ${pattern}`,
          });
          break;
        }
      }

      const errorEls = await page.locator(".error").allInnerTexts();
      for (const err of errorEls.slice(0, 3)) {
        const trimmed = err.trim().slice(0, 200);
        if (trimmed && !issues.some((i) => i.detail.includes(trimmed))) {
          issues.push({ page: entry.path, label: entry.label, detail: trimmed });
        }
      }

      if (entry.mustInclude && !bodyText.includes(entry.mustInclude)) {
        issues.push({
          page: entry.path,
          label: entry.label,
          detail: `Missing expected text "${entry.mustInclude}"`,
        });
      }

      const stillLoading =
        /Loading(…|\.{3})/.test(bodyText) &&
        /Loading parcels|Loading backlog|Loading scoring|Loading parcel counts/i.test(bodyText);
      if (stillLoading) {
        issues.push({
          page: entry.path,
          label: entry.label,
          detail: "Page still showing loading state after settle timeout",
        });
      }

      for (const f of apiFailures.slice(beforeApi)) {
        issues.push({
          page: entry.path,
          label: entry.label,
          detail: `API ${f.status} ${f.url.replace(/^https?:\/\/[^/]+/, "")}`,
        });
      }

      const tableRows = await countTableDataRows(page);
      const zeroGrabVisible = entry.path === "/operator" ? await countVisibleZeroGrabRows(page) : 0;

      pageResults.push({
        path: entry.path,
        label: entry.label,
        ok: issues.filter((i) => i.severity !== "warning").length === 0,
        load_ms: Date.now() - started,
        issues,
        analysis: {
          table_rows: tableRows,
          zero_grab_rows_visible: zeroGrabVisible,
          fully_loaded: !stillLoading,
          scrolled: true,
          refreshed,
        },
      });
    }

    const backlogRaw = await fetchBridgeJson(page, "internal/stats/backlog-eta");
    const governorRaw = await fetchBridgeJson(page, "internal/stats/load-governor");
    const pilotScopeRaw = await fetchBridgeJson(page, "internal/stats/pilot-scope");
    const dealsRaw = (await fetchBridgeJson(page, "internal/pipeline/deal-progress?limit=5")) as {
      summary?: { by_status?: Record<string, number>; total_parcels?: number };
    } | null;
    const waRaw = (await fetchBridgeJson(page, "internal/ingest/wa-rollout-status")) as {
      rollout_enabled?: boolean;
      counties_with_parcels?: number;
      counties_remaining?: number;
      next_county_fips?: string | null;
      parking_queue_depth?: number | null;
      cooldown_ready?: boolean | null;
      last_ingested_county_fips?: string | null;
      last_ingested_county_parcels?: number | null;
      counties?: { county_fips: string; parcels_in_db: number }[];
    } | null;

    const scrapeCoverage = buildScrapeCoverage(
      pilotScopeRaw as Parameters<typeof buildScrapeCoverage>[0],
      waRaw,
      backlogRaw,
    );

    const backlogSummary =
      backlogRaw && typeof backlogRaw === "object" && "summary" in backlogRaw
        ? (backlogRaw as { summary: Record<string, unknown> }).summary
        : {};

    const metrics = {
      backlog_items: backlogCounts(backlogRaw),
      high_value_remaining: Number(backlogSummary.high_value_remaining ?? 0),
      parking_queue_depth: Number(backlogSummary.active_parking_queue_depth ?? 0),
      load_governor_level: String(backlogSummary.load_governor_pressure_level ?? "unknown"),
      wa_rollout_allowed: backlogSummary.wa_rollout_allowed !== false,
      score_gaps: Number(
        (backlogCounts(backlogRaw).score_gaps ?? 0) ||
          (governorRaw && typeof governorRaw === "object" && "score_gaps" in governorRaw
            ? (governorRaw as { score_gaps: number }).score_gaps
            : 0),
      ),
      data_snapshot_at: String(backlogSummary.data_checked_at ?? ""),
      deals_failed: Number(dealsRaw?.summary?.by_status?.failed ?? 0),
      deals_total: Number(dealsRaw?.summary?.total_parcels ?? 0),
      wa_counties_loaded: Number(waRaw?.counties_with_parcels ?? 0),
      wa_counties_remaining: scrapeCoverage.wa_counties_remaining,
      wa_next_county_fips: waRaw?.next_county_fips ?? null,
      wa_cooldown_ready: Boolean(waRaw?.cooldown_ready),
      wa_last_county_parcels: Number(waRaw?.last_ingested_county_parcels ?? 0),
      wa_rollout_enabled: scrapeCoverage.wa_rollout_enabled,
      pilot_county_count: scrapeCoverage.pilot_county_count,
      counties_with_data: scrapeCoverage.counties_with_data,
      counties_zero_grab_count: scrapeCoverage.counties_zero_grab_count,
      backlog_complete: scrapeCoverage.backlog_complete,
      should_advance_counties: scrapeCoverage.should_advance_counties,
      scrape_gaps: scrapeCoverage.scrape_gaps,
    };

    const scrapeWarnings = scrapeGapWarnings(scrapeCoverage.scrape_gaps);
    const blockingIssues = pageResults.flatMap((p) => p.issues.filter((i) => i.severity !== "warning"));
    const allIssues = [...blockingIssues, ...scrapeWarnings];

    const report = {
      checked_at: new Date().toISOString(),
      base_url: process.env.UI_SMOKE_BASE_URL || "https://vspecialist.com",
      status: blockingIssues.length > 0 ? "issues_found" : scrapeWarnings.length > 0 ? "scrape_gaps" : "ok",
      issue_count: allIssues.length,
      blocking_issue_count: blockingIssues.length,
      pages: pageResults,
      metrics,
      scrape_coverage: scrapeCoverage,
      issues: allIssues,
    };
    writeFileSync("agent-report.json", JSON.stringify(report, null, 2));

    if (blockingIssues.length > 0) {
      const summary = blockingIssues.map((i) => `• ${i.label} (${i.page}): ${i.detail}`).join("\n");
      throw new Error(`${blockingIssues.length} operator UI issue(s):\n${summary}`);
    }

    expect(blockingIssues).toHaveLength(0);
  });
});
