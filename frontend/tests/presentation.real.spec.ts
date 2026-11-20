import { expect, test } from "@playwright/test";

const username = process.env.SECURECLOUD_E2E_USERNAME;
const password = process.env.SECURECLOUD_E2E_PASSWORD;

test.skip(
  !username || !password,
  "Presentation capture requires local lab credentials",
);

test("captures the live presentation workflow", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByLabel("Username").fill(username!);
  await page.getByLabel("Password").fill(password!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../runtime/presentation-overview.png",
    fullPage: true,
  });

  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Demo Flow", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "From workload traffic to recovery" }),
  ).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Demo steps" }).getByRole("button"))
    .toHaveCount(6);
  await expect(page.getByText("Demo ready", { exact: true })).toBeVisible();
  await expect(page.getByTitle("RetailCo application")).toBeVisible();

  await page
    .getByRole("navigation", { name: "Demo steps" })
    .getByRole("button", { name: /Normal traffic is permitted/ })
    .click();
  await expect(
    page.getByRole("region", { name: "Live traffic events" }),
  ).toBeVisible();

  await page
    .getByRole("navigation", { name: "Demo steps" })
    .getByRole("button", { name: /Temporal risk is calculated/ })
    .click();
  await expect(
    page.getByRole("table", { name: "Demo temporal risk evidence" }),
  ).toBeVisible();

  await page
    .getByRole("navigation", { name: "Demo steps" })
    .getByRole("button", { name: /The workload is contained/ })
    .click();
  await expect(page.getByText("Triggering evidence", { exact: true })).toBeVisible();
  await page.screenshot({
    path: "../runtime/presentation-demo-flow.png",
    fullPage: true,
  });

  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Tenants & Workloads", exact: true })
    .click();
  await page
    .locator(".table-toolbar select")
    .selectOption({ label: "FacilitiesVendor" });
  await expect(page.locator(".workload-table tbody tr")).toHaveCount(3);
  await page.screenshot({
    path: "../runtime/presentation-workloads.png",
    fullPage: true,
  });

  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Catalog", exact: true })
    .click();
  await expect(
    page.getByRole("table", { name: "Approved application stacks" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../runtime/presentation-catalog.png",
    fullPage: true,
  });

  await page.getByLabel("Tenant scope").selectOption("");
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Network Map", exact: true })
    .click();
  await expect(page.locator(".tenant-zone")).toHaveCount(2);
  await expect(
    page.getByRole("region", { name: "Live traffic events" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../runtime/presentation-network.png",
    fullPage: true,
  });

  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: /^Incidents/ })
    .click();
  await expect(page.getByText("vendor-api", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("vendor-web", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/Unexpected graph edge scored/).first()).toBeVisible();
  await page.screenshot({
    path: "../runtime/presentation-incidents.png",
    fullPage: true,
  });
});
