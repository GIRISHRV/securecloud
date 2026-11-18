import { expect, test } from "@playwright/test";

const username = process.env.SECURECLOUD_E2E_USERNAME;
const password = process.env.SECURECLOUD_E2E_PASSWORD;

test.skip(
  !username || !password,
  "Real portal credentials were not supplied for the local lab",
);

test("deploys, observes, stops, and deletes a real Kubernetes workload", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Username").fill(username!);
  await page.getByLabel("Password").fill(password!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();

  await page
    .getByRole("button", { name: "Create your first tenant" })
    .click();
  await page.getByLabel("Tenant name", { exact: true }).fill("E2E Tenant");
  await page.getByLabel("Description (optional)").fill("Real portal validation");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Create tenant", exact: true })
    .click();

  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Catalog", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Deploy web app", exact: true })
    .click();
  await page.getByLabel("Workload name").fill("portal-e2e-web");
  await page
    .getByRole("button", { name: "Deploy workload", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "portal-e2e-web is running in E2E Tenant",
  );

  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Tenants & Workloads", exact: true })
    .click();
  await page
    .getByRole("button", { name: "portal-e2e-web", exact: true })
    .click();
  const details = page.getByRole("dialog");
  await expect(details).toContainText("Kubernetes UID");
  await expect(details).not.toContainText("Not observed");

  await details
    .getByRole("button", { name: "Stop workload", exact: true })
    .click();
  await page.getByLabel("Type portal-e2e-web to stop").fill("portal-e2e-web");
  await page.getByRole("button", { name: "Confirm stop" }).click();
  await expect(page.locator("tbody")).toContainText("stopped");

  await page
    .getByRole("button", { name: "portal-e2e-web", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete workload", exact: true })
    .click();
  await page
    .getByLabel("Type portal-e2e-web to delete")
    .fill("portal-e2e-web");
  await page.getByRole("button", { name: "Confirm delete" }).click();
  await expect(
    page.getByText("No workloads found", { exact: true }),
  ).toBeVisible();
});

test("renders the real tenant topology without empty workload placeholders", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Username").fill(username!);
  await page.getByLabel("Password").fill(password!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Network Map", exact: true })
    .click();

  await expect(page.locator(".tenant-zone").filter({ hasText: "School" })).toBeVisible();
  await expect(page.locator(".tenant-zone").filter({ hasText: "Hospital" })).toBeVisible();
  await expect(page.getByText(/No (api|database) workload/i)).toHaveCount(0);
  await page.screenshot({
    path: "../runtime/topology-preview.png",
    fullPage: true,
  });
});

test("renders the reconciled retail stack from the management API", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Username").fill(username!);
  await page.getByLabel("Password").fill(password!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();

  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Tenants & Workloads", exact: true })
    .click();

  const workloadRows = page.locator(".workload-table tbody tr");
  await expect(workloadRows).toHaveCount(12);
  await expect(page.getByRole("button", { name: "frontend", exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "checkoutservice", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".workload-table tbody")).toContainText("RetailCo");
  await expect(page.locator(".workload-table tbody")).toContainText("running");

  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Catalog", exact: true })
    .click();
  const retailRow = page
    .getByRole("table", { name: "Approved application stacks" })
    .getByRole("row", { name: /Retail application/ });
  await expect(retailRow).toContainText("12");
  await expect(retailRow.getByRole("button", { name: "Deploy stack" })).toBeEnabled();
});
