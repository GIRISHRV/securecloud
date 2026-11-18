import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const nav = (page: Page, name: string) =>
  page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name, exact: true });
async function openNetwork(page: Page) {
  await nav(page, "Network Map").click();
}
async function loadDemo(page: Page) {
  await page.getByRole("button", { name: "Load demo", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Load demo", exact: true }),
  ).toHaveCount(0);
}
async function createAlert(page: Page) {
  await loadDemo(page);
  await openNetwork(page);
  await page
    .getByRole("button", { name: "Cross-tenant attempt", exact: true })
    .click();
  await page.getByRole("button", { name: "Send 3 attempts" }).click();
  await nav(page, "Incidents 1").click();
}
test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("starts empty and only loads sample tenants on request", async ({
  page,
}) => {
  await expect(
    page.getByRole("heading", { name: "Build your first workspace" }),
  ).toBeVisible();
  await expect(page.locator(".resource-metric>strong")).toHaveText([
    "0",
    "0",
    "0",
    "0",
  ]);
  await page.reload();
  await expect(page.locator(".resource-metric>strong")).toHaveText([
    "0",
    "0",
    "0",
    "0",
  ]);
  await nav(page, "Catalog").click();
  const stacks = page.getByRole("table", {
    name: "Approved application stacks",
  });
  await expect(stacks).toBeVisible();
  await expect(stacks.getByText("Retail application")).toBeVisible();
  await expect(stacks.getByText("Facilities vendor application")).toBeVisible();
  await expect(stacks.getByText("Adapter pending")).toHaveCount(2);
  await expect(
    page.getByRole("button", { name: "Deploy web app", exact: true }),
  ).toBeDisabled();
  await loadDemo(page);
  await expect(page.locator(".resource-metric>strong")).toHaveText([
    "2",
    "6",
    "0",
    "0",
  ]);
  await page.reload();
  await expect(page.locator(".resource-metric>strong")).toHaveText([
    "2",
    "6",
    "0",
    "0",
  ]);
});

test("creates custom tenants, deploys to a third tenant, and scopes views", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Create your first tenant" }).click();
  await page.getByLabel("Tenant name", { exact: true }).fill("Research");
  await page
    .getByLabel("Description (optional)")
    .fill("Experiments and analysis");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Create tenant", exact: true })
    .click();
  await expect(page.locator(".tenant-card")).toHaveCount(1);
  await loadDemo(page);
  await expect(page.locator(".resource-metric>strong")).toHaveText([
    "3",
    "6",
    "0",
    "0",
  ]);
  await page
    .getByLabel("Tenant scope", { exact: true })
    .selectOption({ label: "Research" });
  await expect(page.locator(".resource-metric>strong")).toHaveText([
    "1",
    "0",
    "0",
    "0",
  ]);
  for (const [button, name] of [
    ["Deploy web app", "research-web"],
    ["Deploy API", "research-api"],
  ]) {
    await nav(page, "Catalog").click();
    await page.getByRole("button", { name: button, exact: true }).click();
    await expect(
      page
        .getByRole("dialog")
        .getByLabel("Tenant", { exact: true })
        .locator("option:checked"),
    ).toHaveText("Research");
    await page.getByLabel("Workload name").fill(name);
    await page.getByRole("button", { name: "Create demo workload" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
  await nav(page, "Tenants & Workloads").click();
  await expect(page.locator("tbody tr")).toHaveCount(2);
  await openNetwork(page);
  await expect(page.locator(".tenant-zone")).toHaveCount(1);
  await page
    .getByRole("button", { name: "Simulate connection", exact: true })
    .click();
  await expect(page.locator(".decision-result")).toContainText("allowed");
  await page
    .getByRole("button", { name: "Cross-tenant attempt", exact: true })
    .click();
  await page.getByRole("button", { name: "Send 3 attempts" }).click();
  await expect(page.locator(".decision-result")).toContainText("denied");
  await nav(page, "Incidents 1").click();
  await expect(page.locator(".incident-card")).toContainText("Research");
  await page.reload();
  await page
    .getByLabel("Tenant scope", { exact: true })
    .selectOption({ label: "Research" });
  await expect(page.locator(".incident-card")).toContainText("research-web");
  await page
    .getByLabel("Tenant scope", { exact: true })
    .selectOption({ label: "All tenants" });
  await nav(page, "Tenants & Workloads").click();
  await expect(page.locator(".tenant-card")).toHaveCount(3);
  await expect(page.locator("tbody tr")).toHaveCount(8);
});

test("searches resources and supports a collapsible navigation rail", async ({
  page,
}) => {
  await loadDemo(page);
  await page.getByLabel("Search resources and services").fill("college-web");
  await page
    .getByRole("region", { name: "Search results" })
    .getByRole("button", { name: "college-web College" })
    .click();
  await expect(page.getByRole("dialog")).toContainText("college-web");
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.getByLabel("Search resources and services").fill("Network Map");
  await page
    .getByRole("region", { name: "Search results" })
    .getByRole("button", { name: "Network Map Service" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Network Map", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toBeHidden();
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toBeVisible();
});

test("simulates an allowed path and a full incident response with persistence", async ({
  page,
}) => {
  await loadDemo(page);
  await openNetwork(page);
  await page
    .getByRole("button", { name: "Simulate connection", exact: true })
    .click();
  await expect(page.locator(".decision-result")).toContainText("allowed");
  await page
    .getByRole("button", { name: "Cross-tenant attempt", exact: true })
    .click();
  await page.getByRole("button", { name: "Send 3 attempts" }).click();
  await expect(page.locator(".decision-result")).toContainText("denied");
  await nav(page, "Incidents 1").click();
  await expect(page.locator(".incident-card")).toHaveCount(1);
  await expect(page.locator(".trace")).toContainText("Detection: alert raised");
  await page
    .getByRole("button", { name: "Quarantine workload", exact: true })
    .click();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Start review" }),
  ).toBeVisible();
  await openNetwork(page);
  await page
    .getByRole("button", { name: "Simulate connection", exact: true })
    .click();
  await expect(page.locator(".decision-result")).toContainText(
    "Quarantine overrides approved intents",
  );
  await nav(page, "Incidents 1").click();
  await page.getByRole("button", { name: "Start review" }).click();
  await page
    .getByRole("button", { name: "Restore workload", exact: true })
    .click();
  await expect(page.locator(".trace")).toContainText("Response: restored");
  await openNetwork(page);
  await page
    .getByRole("button", { name: "Simulate connection", exact: true })
    .click();
  await expect(page.locator(".decision-result")).toContainText("allowed");
});

test("deploys, inspects, stops, deletes and resets local workloads", async ({
  page,
}) => {
  await loadDemo(page);
  await nav(page, "Catalog").click();
  await page
    .getByRole("button", { name: "Deploy web app", exact: true })
    .click();
  await page.getByLabel("Workload name").fill("demo-website");
  await page.getByRole("button", { name: "Create demo workload" }).click();
  await expect(page.getByRole("status")).toContainText("demo-website deployed");
  await page.reload();
  await nav(page, "Tenants & Workloads").click();
  await page.getByLabel("Search workloads").fill("demo-website");
  await page
    .getByRole("button", { name: "demo-website", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("0.25 vCPU");
  await page
    .getByRole("button", { name: "Stop workload", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Confirm stop" }),
  ).toBeDisabled();
  await page.getByLabel("Type demo-website to stop").fill("demo-website");
  await page.getByRole("button", { name: "Confirm stop" }).click();
  await expect(page.locator("tbody")).toContainText("stopped");
  await page
    .getByRole("button", { name: "demo-website", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete workload", exact: true })
    .click();
  await page.getByLabel("Type demo-website to delete").fill("demo-website");
  await page.getByRole("button", { name: "Confirm delete" }).click();
  await expect(
    page.getByText("No workloads found", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Clear workspace", exact: true })
    .click();
  const dialogOffset = await page.getByRole("dialog").evaluate((dialog) => {
    const bounds = dialog.getBoundingClientRect();
    return Math.abs(bounds.left + bounds.width / 2 - window.innerWidth / 2);
  });
  expect(dialogOffset).toBeLessThan(2);
  await page.getByRole("button", { name: "Clear all local data" }).click();
  await nav(page, "Tenants & Workloads").click();
  await expect(page.locator("tbody tr")).toHaveCount(0);
  await expect(page.getByText("No tenants yet", { exact: true })).toBeVisible();
});

test("supports keyboard navigation, modal dismissal, and exact name protection", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name === "mobile",
    "Physical keyboard workflow is checked on desktop.",
  );
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Skip to content" }),
  ).toBeFocused();
  const commands = page.getByRole("toolbar", { name: "Workspace commands" });
  await commands.getByRole("button", { name: "Create tenant" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    commands.getByRole("button", { name: "Deploy workload" }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.locator(".resource-metric").first()).toBeFocused();
  await loadDemo(page);
  await nav(page, "Catalog").focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Catalog", exact: true }),
  ).toBeFocused();
  const deploy = page.getByRole("button", { name: "Deploy API", exact: true });
  await deploy.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(deploy).toBeFocused();
});

test("handles storage corruption and empty tenants without crashing", async ({
  page,
}) => {
  await page.evaluate(() =>
    localStorage.setItem("securecloud:workspace:v2", "{broken"),
  );
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("could not be loaded");
  await page
    .getByRole("button", { name: "Clear workspace", exact: true })
    .click();
  await page.getByRole("button", { name: "Clear all local data" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.evaluate(() => {
    const saved = JSON.parse(localStorage.getItem("securecloud:workspace:v2")!);
    saved.workloads = [];
    localStorage.setItem("securecloud:workspace:v2", JSON.stringify(saved));
  });
  await page.reload();
  await openNetwork(page);
  await expect(
    page.getByRole("button", { name: "Simulate connection", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("Your network starts here", { exact: true }),
  ).toBeVisible();
});

test("has accessible views and no page overflow at the target viewport", async ({
  page,
}) => {
  for (const populated of [false, true]) {
    if (populated) await loadDemo(page);
    for (const view of [
      "Overview",
      "Tenants & Workloads",
      "Catalog",
      "Network Map",
      "Incidents",
    ]) {
      await nav(page, view).click();
      await expect(
        page.getByRole("heading", { name: view, exact: true }),
      ).toBeVisible();
      const pageWidth = await page.evaluate(() => ({
        content: document.documentElement.scrollWidth,
        viewport: window.innerWidth,
      }));
      expect(pageWidth.content).toBeLessThanOrEqual(pageWidth.viewport);
      const results = await new AxeBuilder({ page })
        // Ignore framework focus guards; assert the first real interactive control.
        // Keyboard entry, arrow navigation, and exit are exercised above.
        .exclude("[data-tabster-dummy]")
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      expect(
        results.violations.map((v) => ({
          id: v.id,
          nodes: v.nodes.map((n) => ({
            target: n.target,
            summary: n.failureSummary,
          })),
        })),
      ).toEqual([]);
    }
  }
});

test("incident details and deployment dialog remain accessible", async ({
  page,
}) => {
  await createAlert(page);
  let results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => n.target),
    })),
  ).toEqual([]);
  await nav(page, "Catalog").click();
  await page
    .getByRole("button", { name: "Deploy web app", exact: true })
    .click();
  results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => n.target),
    })),
  ).toEqual([]);
});

test("captures the overview and network map without browser errors", async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.reload();
  await page.screenshot({
    path: testInfo.outputPath("overview.png"),
    fullPage: true,
  });
  await loadDemo(page);
  await page.screenshot({
    path: testInfo.outputPath("demo-overview.png"),
    fullPage: true,
  });
  await nav(page, "Catalog").click();
  await expect(
    page.getByRole("table", { name: "Approved templates" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("catalog.png"),
    fullPage: true,
  });
  await nav(page, "Tenants & Workloads").click();
  await expect(page.getByRole("table")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("workloads.png"),
    fullPage: true,
  });
  await openNetwork(page);
  await expect(
    page.getByRole("heading", { name: "Tenant network topology" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("network.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
