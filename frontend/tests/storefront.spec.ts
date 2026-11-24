import { expect, test, type Page } from "@playwright/test";

const user = {
  id: "user-alice",
  tenant_id: "retailco",
  email: "alice@example.test",
  display_name: "Alice Rao",
  phone: "9876543210",
  role: "customer",
  status: "active",
};

const product = {
  id: "prod-backpack",
  sku: "NS-BAG-01",
  name: "Everyday Backpack",
  description: "A practical backpack for work and travel.",
  price_minor: 249900,
  currency: "INR",
  stock_quantity: 20,
  published: true,
  image_path: "",
  created_at: 1,
  updated_at: 1,
};

const emptyCart = { id: "cart-alice", items: [], subtotal_minor: 0, currency: "INR" };
const filledCart = {
  ...emptyCart,
  items: [{
    product_id: product.id,
    quantity: 1,
    unit_price_minor: product.price_minor,
    sku: product.sku,
    name: product.name,
    stock_quantity: product.stock_quantity,
    published: 1,
    line_total_minor: product.price_minor,
  }],
  subtotal_minor: product.price_minor,
};

async function mockRetail(page: Page) {
  let signedIn = false;
  let cart: typeof filledCart = { ...emptyCart, items: [] };
  let orders: unknown[] = [];

  await page.route("**/api/retail/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const json = (value: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });

    if (path === "/api/retail/products") return json({ items: [product] });
    if (path === "/api/retail/auth/session") {
      return signedIn ? json({ user, csrf: "csrf-token-123456789", session_id: "session-alice" }) : json({ detail: "Sign in" }, 401);
    }
    if (path === "/api/retail/auth/register") return json({ user }, 201);
    if (path === "/api/retail/auth/login") {
      signedIn = true;
      return json({ user, csrf: "csrf-token-123456789", session_id: "session-alice" });
    }
    if (path === "/api/retail/cart/items" && request.method() === "POST") {
      cart = filledCart;
      return json(cart);
    }
    if (path === "/api/retail/cart") return json(cart);
    if (path === "/api/retail/orders") return json({ items: orders });
    if (path === "/api/retail/checkout") {
      const body = request.postDataJSON();
      const order = {
        id: "order-1",
        order_number: "NS-2026-0001",
        user_id: user.id,
        tenant_id: user.tenant_id,
        status: "placed",
        payment_status: "paid",
        subtotal_minor: product.price_minor,
        total_minor: product.price_minor,
        currency: "INR",
        created_at: 1_795_200_000,
        updated_at: 1_795_200_000,
        customer: { id: user.id, name: user.display_name, email: user.email, phone: user.phone },
        delivery_address: body,
        items: [{ id: "item-1", order_id: "order-1", product_id: product.id, sku_snapshot: product.sku, name_snapshot: product.name, unit_price_minor: product.price_minor, quantity: 1 }],
        payment: { provider: "simulator", reference: "PAY-TEST-001", amount_minor: product.price_minor, status: "paid", created_at: 1_795_200_000 },
      };
      orders = [order];
      cart = emptyCart;
      return json(order, 201);
    }
    return json({ detail: `Unhandled test route: ${request.method()} ${path}` }, 500);
  });
}

test("customer registers, checks out, and reopens the order", async ({ page }) => {
  await mockRetail(page);
  await page.goto("/shop");

  await expect(page.getByRole("heading", { name: /Everyday goods/ })).toBeVisible();
  await expect(page.getByText("Everyday Backpack", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Add Everyday Backpack to cart" }).click();

  await expect(page).toHaveURL(/\/shop\/login$/);
  await page.getByRole("button", { name: "Create an account" }).click();
  await page.getByLabel("Full name").fill(user.display_name);
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Phone").fill(user.phone);
  await page.locator('input[name="password"]').fill("correct-horse-battery-staple");
  await page.getByLabel("Confirm password").fill("correct-horse-battery-staple");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill("correct-horse-battery-staple");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("button", { name: "Add Everyday Backpack to cart" }).click();
  await expect(page.getByRole("link", { name: /Cart 1/ })).toBeVisible();
  await page.getByRole("link", { name: /Cart 1/ }).click();
  await page.getByRole("button", { name: "Continue to checkout" }).click();

  await page.getByLabel("Address line 1").fill("42 Lake View Road");
  await page.getByLabel("City").fill("Bengaluru");
  await page.getByLabel("State").fill("Karnataka");
  await page.getByLabel("Postal code").fill("560001");
  await page.getByRole("button", { name: /Pay .* and place order/ }).click();

  await expect(page.getByRole("heading", { name: "NS-2026-0001" })).toBeVisible();
  await expect(page.getByText("PAY-TEST-001")).toBeVisible();
  await expect(page.getByText("Paid", { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "All orders" }).click();
  await page.getByRole("link", { name: /NS-2026-0001/ }).click();
  await expect(page.getByText("PAY-TEST-001")).toBeVisible();
});
