import { expect, test, type Page, type Response } from "@playwright/test";
import { writeFileSync } from "node:fs";

/** Operator + approval UI pages an admin uses daily. */
const ADMIN_PAGES: { path: string; label: string; mustInclude?: string }[] = [
  { path: "/operator", label: "Operator overview", mustInclude: "Operator overview" },
  { path: "/operator/outreach", label: "Outreach pipeline", mustInclude: "Outreach pipeline" },
  { path: "/operator/deals", label: "Deal progress", mustInclude: "Deal progress" },
  { path: "/operator/approvals", label: "Operator approvals" },
  { path: "/operator/parcels", label: "Parcels", mustInclude: "Parcels" },
  { path: "/", label: "Approval home" },
];

type ApiFailure = { status: number; url: string; page: string };
type PageIssue = { page: string; label: string; detail: string };

function attachApiTracker(page: Page, getLabel: () => string, sink: ApiFailure[]) {
  page.on("response", (res: Response) => {
    const url = res.url();
    if (!url.includes("/api/bridge/") && !url.includes("/api/proxy/")) return;
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
  await page.getByLabel("Email or username").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 30_000 });
}

test.describe("Admin UI smoke", () => {
  test("login and key pages load without API or visible errors", async ({ page }) => {
    const apiFailures: ApiFailure[] = [];
    const pageIssues: PageIssue[] = [];
    let currentLabel = "login";
    attachApiTracker(page, () => currentLabel, apiFailures);

    await loginAsAdmin(page);

    for (const entry of ADMIN_PAGES) {
      currentLabel = entry.label;
      const beforeApi = apiFailures.length;

      const response = await page.goto(entry.path, { waitUntil: "domcontentloaded" });
      await page.waitForLoadState("networkidle", { timeout: 25_000 }).catch(() => undefined);

      const status = response?.status() ?? 0;
      if (status >= 400) {
        pageIssues.push({
          page: entry.path,
          label: entry.label,
          detail: `HTTP ${status} on navigation`,
        });
      }

      const title = await page.title();
      if (/404|not found/i.test(title)) {
        pageIssues.push({ page: entry.path, label: entry.label, detail: `Page title: ${title}` });
      }

      const bodyText = (await page.locator("body").innerText()).slice(0, 8000);
      for (const pattern of [/HTTP 503/i, /HTTP 502/i, /HTTP 404/i, /INTERNAL_API_KEY not configured/i]) {
        if (pattern.test(bodyText)) {
          pageIssues.push({
            page: entry.path,
            label: entry.label,
            detail: `Visible error text matched ${pattern}`,
          });
          break;
        }
      }

      if (entry.mustInclude && !bodyText.includes(entry.mustInclude)) {
        pageIssues.push({
          page: entry.path,
          label: entry.label,
          detail: `Missing expected heading "${entry.mustInclude}"`,
        });
      }

      for (const f of apiFailures.slice(beforeApi)) {
        pageIssues.push({
          page: entry.path,
          label: entry.label,
          detail: `API ${f.status} ${f.url.replace(/^https?:\/\/[^/]+/, "")}`,
        });
      }
    }

    const report = {
      checked_at: new Date().toISOString(),
      base_url: process.env.UI_SMOKE_BASE_URL || "https://vspecialist.com",
      status: pageIssues.length > 0 ? "ui_failed" : "ok",
      issue_count: pageIssues.length,
      issues: pageIssues,
    };
    writeFileSync("smoke-report.json", JSON.stringify(report, null, 2));

    if (pageIssues.length > 0) {
      const summary = pageIssues.map((i) => `• ${i.label} (${i.page}): ${i.detail}`).join("\n");
      throw new Error(`${pageIssues.length} UI issue(s) found:\n${summary}`);
    }

    expect(pageIssues).toHaveLength(0);
  });
});
