import { expect, test, type Page } from "@playwright/test";

const owner = { id: "owner-1", tenant_id: "retailco", email: "owner@example.test", display_name: "Store Owner", phone: "", role: "owner", status: "active" };
const customer = { id: "alice-1", email: "alice@example.test", display_name: "Alice Rao", phone: "+91 9876543210", status: "active", created_at: 1_795_100_000, order_count: 1, total_spent_minor: 249900, last_seen_at: 1_795_200_000 };
const product = { id: "prod-1", sku: "NS-BAG-01", name: "Everyday Backpack", description: "A practical backpack.", price_minor: 249900, currency: "INR", stock_quantity: 19, published: true, image_path: "", created_at: 1, updated_at: 1 };

async function mockAdmin(page: Page) {
  let signedIn = false;
  let status = "placed";
  let incidentStatus = "alert";
  const applicationEvent = { id: "app-event-1", occurred_at: 1_795_200_000, request_id: "request-1", tenant_id: "retailco", actor_id: customer.id, session_id: "session-alice", source_workload: "vendor-api", destination_workload: "paymentservice", action: "vendor.payment_attempt", route_template: "/payment", result: "blocked", protocol: "TCP", destination_port: 8080, correlation: { application_event_id: "app-event-1", flow_event_id: "flow-1", status: "exact", reason: "one resolved flow matched identity, protocol, port, and time window", correlated_at: 1_795_200_001, observed_at: 1_795_200_000, source_workload: "vendor-api-id", source_name: "vendor-api", destination_workload: "payment-id", destination_name: "paymentservice", verdict: "dropped", drop_reason: "POLICY_DENIED", protocol: "TCP", destination_port: 8080 } };
  const traffic = { id: "flow-1", at: 1_795_200_000, sourceId: "vendor-api-id", destinationId: "payment-id", sourceName: "vendor-api", destinationName: "paymentservice", sourceTenant: "vendor", destinationTenant: "retailco", port: 8080, decision: "denied", reason: "cross-tenant" };
  const security = () => ({ applicationEvents: [applicationEvent], traffic: [traffic], risk: [{ modelVersion: "gconvgru-v1", windowStart: 1_795_199_970, windowEnd: 1_795_200_000, sourceId: "vendor-api-id", destinationId: "payment-id", sourceName: "vendor-api", destinationName: "paymentservice", anomalyScore: 0.91, accumulatedRisk: 0.87, baselineScore: 0.22, threshold: 0.5, corroborated: true, response: "containment-recommended", tenantId: "vendor" }], incidents: [{ id: "incident-1", sourceId: "vendor-api-id", sourceName: "vendor-api", tenantId: "vendor", status: incidentStatus, reason: "Unusual vendor traffic followed by a forbidden payment request", createdAt: 1_795_200_000, restoredAt: null, evidence: [traffic], trace: [{ at: 1_795_200_000, title: "Graph anomaly detected", detail: "Temporal risk crossed the calibrated threshold with a policy denial." }], applicationEvents: [applicationEvent], finding: { model_version: "gconvgru-v1", anomaly_score: 0.91, accumulated_risk: 0.87, baseline_score: 0.22, threshold: 0.5, response: "containment-recommended", supporting_facts: { policy_denied: true, cross_tenant: true }, event_ids: ["flow-1"] }, containment: incidentStatus === "alert" ? null : { status: "succeeded", action: "quarantine", error: null } }] });
  const order = () => ({
    id: "order-1", order_number: "NS-2026-0001", user_id: customer.id, tenant_id: "retailco", status,
    payment_status: "paid", subtotal_minor: 249900, total_minor: 249900, currency: "INR", created_at: 1_795_200_000, updated_at: 1_795_200_000,
    customer: { id: customer.id, name: customer.display_name, email: customer.email, phone: customer.phone },
    delivery_address: { recipient: customer.display_name, line1: "42 Lake View Road", line2: "", city: "Bengaluru", state: "Karnataka", postal_code: "560001", phone: customer.phone },
    items: [{ id: "item-1", order_id: "order-1", product_id: product.id, sku_snapshot: product.sku, name_snapshot: product.name, unit_price_minor: product.price_minor, quantity: 1 }],
    payment: { provider: "simulator", reference: "PAY-001", amount_minor: 249900, status: "paid", created_at: 1_795_200_000 },
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (value: unknown, code = 200) => route.fulfill({ status: code, contentType: "application/json", body: JSON.stringify(value) });
    if (path === "/api/retail/auth/session") return signedIn ? json({ user: owner, csrf: "csrf-owner-123456", session_id: "session-owner" }) : json({ detail: "Sign in" }, 401);
    if (path === "/api/retail/auth/login") { signedIn = true; return json({ user: owner, csrf: "csrf-owner-123456", session_id: "session-owner" }); }
    if (path === "/api/retail/admin/overview") return json({ orders_today: 1, revenue_today_minor: 249900, open_orders: 1, active_customers: 1, currency: "INR" });
    if (path === "/api/retail/admin/customers") return json({ items: [customer] });
    if (path === "/api/retail/admin/sessions") return json({ items: [{ id: "session-alice", created_at: 1_795_100_000, expires_at: 1_795_900_000, last_seen_at: 1_795_200_000, client_summary: "Edge on Windows", user_id: customer.id, email: customer.email, display_name: customer.display_name, role: "customer", active: true }] });
    if (path === "/api/retail/admin/products") return json({ items: [product] });
    if (path === "/api/retail/admin/orders") return json({ items: [order()] });
    if (path === "/api/retail/admin/activity") return json({ items: [{ id: "event-1", occurred_at: 1_795_200_000, request_id: "request-1", tenant_id: "retailco", actor_id: customer.id, session_id: "session-alice", source_workload: "frontend", destination_workload: "checkoutservice", action: "order.checkout", route_template: "/api/retail/checkout", result: "paid", protocol: "TCP", destination_port: 8080 }] });
    if (path === "/api/retail/admin/security/summary") return json(security());
    if (path === "/api/health") return json({ status: "ok" });
    if (path === "/api/retail/admin/orders/order-1/status" && request.method() === "PATCH") { status = request.postDataJSON().status; return json(order()); }
    if (path === "/api/retail/admin/security/incidents/incident-1/quarantine" && request.method() === "POST") { incidentStatus = "quarantined"; return json({ status: "quarantined", verified: true }); }
    return json({ detail: `Unhandled test route: ${request.method()} ${path}` }, 500);
  });
}

async function openNavigation(page: Page) {
  const menu = page.getByRole("button", { name: "Toggle admin navigation" });
  if (await menu.isVisible()) await menu.click();
}

test("owner signs in, sees the customer order, and advances fulfilment", async ({ page }) => {
  await mockAdmin(page);
  await page.goto("/admin");
  await page.getByLabel("Email").fill(owner.email);
  await page.getByLabel("Password").fill("correct-horse-battery-staple");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Store overview" })).toBeVisible();
  await expect(page.getByText("Alice Rao", { exact: true })).toBeVisible();

  await openNavigation(page);
  await page.getByRole("navigation", { name: "Admin navigation" }).getByRole("button", { name: "Orders" }).click();
  await page.getByLabel("Status for NS-2026-0001").selectOption("processing");
  await expect(page.getByLabel("Status for NS-2026-0001")).toHaveValue("processing");

  await openNavigation(page);
  await page.getByRole("navigation", { name: "Admin navigation" }).getByRole("button", { name: "Customers" }).click();
  await expect(page.getByRole("heading", { name: "Customers and sessions" })).toBeVisible();
  await expect(page.getByText("Edge on Windows")).toBeVisible();

  await openNavigation(page);
  await page.getByRole("navigation", { name: "Admin navigation" }).getByRole("button", { name: "Products" }).click();
  await expect(page.getByText("Everyday Backpack", { exact: true })).toBeVisible();

  await openNavigation(page);
  await page.getByRole("button", { name: "Security activity" }).click();
  await expect(page.getByRole("heading", { name: "Security activity" })).toBeVisible();
  await expect(page.getByText("GNN anomaly")).toBeVisible();
  const quarantine = page.getByRole("button", { name: "Quarantine workload" });
  await quarantine.hover();
  await page.mouse.down();
  await page.waitForTimeout(1600);
  await page.mouse.up();
  await expect(page.getByText("quarantined", { exact: true }).first()).toBeVisible();
});
