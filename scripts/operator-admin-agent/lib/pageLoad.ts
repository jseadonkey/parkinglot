import type { Page } from "@playwright/test";

/** Scroll the main content so lazy sections and long tables render. */
export async function scrollFullPage(page: Page) {
  await page.evaluate(async () => {
    const main = document.querySelector(".app-main") ?? document.documentElement;
    const step = Math.max(240, Math.floor(window.innerHeight * 0.75));
    let y = 0;
    const maxY = Math.max(main.scrollHeight, document.body.scrollHeight) - window.innerHeight;
    while (y < maxY) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 120));
      y += step;
    }
    window.scrollTo(0, 0);
  });
}

/** Click a visible Refresh control when the page exposes one. */
export async function tryClickRefresh(page: Page) {
  const refresh = page.getByRole("button", { name: /^Refresh/i });
  if ((await refresh.count()) > 0 && (await refresh.first().isVisible())) {
    await refresh.first().click();
    await page.waitForTimeout(2_000);
  }
}

/** On Overview, expand the full pilot county table when the toggle is present. */
export async function expandOverviewCounties(page: Page) {
  const toggle = page.getByRole("button", { name: /Show all \d+ pilot counties/i });
  if ((await toggle.count()) > 0 && (await toggle.first().isVisible())) {
    await toggle.first().click();
    await page.waitForTimeout(1_000);
  }
}

/** Count data rows in the first table on the page (excludes header). */
export async function countTableDataRows(page: Page): Promise<number> {
  return page.evaluate(() => {
    const table = document.querySelector("table.data tbody") ?? document.querySelector("table tbody");
    if (!table) return 0;
    return table.querySelectorAll("tr").length;
  });
}

/** Count scope-county rows showing 0 parcels in DB (visible in Overview table). */
export async function countVisibleZeroGrabRows(page: Page): Promise<number> {
  return page.evaluate(() => {
    const rows = document.querySelectorAll("table.scope-county-table tbody tr, table.data tbody tr");
    let n = 0;
    for (const row of rows) {
      const cells = row.querySelectorAll("td");
      if (cells.length === 0) continue;
      const last = cells[cells.length - 1]?.textContent?.replace(/,/g, "").trim() ?? "";
      if (last === "0") n += 1;
    }
    return n;
  });
}
