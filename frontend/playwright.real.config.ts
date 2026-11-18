import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 95_000 },
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4174",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    browserName: "chromium",
    channel: "msedge",
    viewport: { width: 1440, height: 1000 },
  },
});
