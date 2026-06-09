import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.UI_SMOKE_BASE_URL?.replace(/\/$/, "") || "https://vspecialist.com";

export default defineConfig({
  testDir: "./tests",
  timeout: 240_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["json", { outputFile: "agent-report.json" }]],
  use: {
    baseURL,
    ...devices["Desktop Chrome"],
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
