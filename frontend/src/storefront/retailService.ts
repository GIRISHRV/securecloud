import { z } from "zod";

const userSchema = z.object({
  id: z.string().min(1),
  tenant_id: z.string().min(1),
  email: z.string().min(3),
  display_name: z.string().min(1),
  phone: z.string(),
  role: z.enum(["customer", "owner"]),
  status: z.literal("active"),
});

export const productSchema = z.object({
  id: z.string().min(1),
  sku: z.string().min(1),
  name: z.string().min(1),
  description: z.string(),
  price_minor: z.number().int().nonnegative(),
  currency: z.literal("INR"),
  stock_quantity: z.number().int().nonnegative(),
  published: z.boolean(),
  image_path: z.string(),
  created_at: z.number(),
  updated_at: z.number(),
});

const cartItemSchema = z.object({
  product_id: z.string(),
  quantity: z.number().int().positive(),
  unit_price_minor: z.number().int().nonnegative(),
  sku: z.string(),
  name: z.string(),
  stock_quantity: z.number().int().nonnegative(),
  published: z.number().int(),
  image_path: z.string().default(""),
  line_total_minor: z.number().int().nonnegative(),
});

export const cartSchema = z.object({
  id: z.string(),
  items: z.array(cartItemSchema),
  subtotal_minor: z.number().int().nonnegative(),
  currency: z.literal("INR"),
});

const orderItemSchema = z.object({
  id: z.string(),
  order_id: z.string(),
  product_id: z.string(),
  sku_snapshot: z.string(),
  name_snapshot: z.string(),
  unit_price_minor: z.number().int().nonnegative(),
  quantity: z.number().int().positive(),
});

export const orderSchema = z.object({
  id: z.string(),
  order_number: z.string(),
  user_id: z.string(),
  tenant_id: z.string(),
  status: z.enum(["placed", "processing", "packing", "shipped", "delivered", "cancelled"]),
  payment_status: z.enum(["paid", "failed", "refunded"]),
  subtotal_minor: z.number().int().nonnegative(),
  total_minor: z.number().int().nonnegative(),
  currency: z.literal("INR"),
  created_at: z.number(),
  updated_at: z.number(),
  customer: z.object({ id: z.string(), name: z.string(), email: z.string(), phone: z.string() }),
  delivery_address: z.object({
    recipient: z.string(), line1: z.string(), line2: z.string(), city: z.string(),
    state: z.string(), postal_code: z.string(), phone: z.string(),
  }),
  items: z.array(orderItemSchema),
  payment: z.object({
    provider: z.literal("simulator"), reference: z.string(), amount_minor: z.number().int(),
    status: z.enum(["paid", "failed", "refunded"]), created_at: z.number(),
  }).nullable(),
});

const sessionSchema = z.object({ user: userSchema, csrf: z.string().min(16), session_id: z.string() });
const productsSchema = z.object({ items: z.array(productSchema) });
const ordersSchema = z.object({ items: z.array(orderSchema) });
const errorSchema = z.object({ detail: z.string() });

export type RetailUser = z.infer<typeof userSchema>;
export type Product = z.infer<typeof productSchema>;
export type Cart = z.infer<typeof cartSchema>;
export type Order = z.infer<typeof orderSchema>;

export class RetailService {
  private csrf = "";

  private async error(response: Response, fallback: string) {
    const parsed = errorSchema.safeParse(await response.json().catch(() => null));
    return new Error(parsed.success ? parsed.data.detail : fallback);
  }

  private mutationHeaders(idempotencyKey?: string) {
    return {
      "Content-Type": "application/json",
      ...(this.csrf ? { "X-CSRF-Token": this.csrf } : {}),
      ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
    };
  }

  async session() {
    const response = await fetch("/api/retail/auth/session");
    if (response.status === 401) return null;
    if (!response.ok) throw await this.error(response, "Could not check your session");
    const value = sessionSchema.parse(await response.json());
    this.csrf = value.csrf;
    return value.user;
  }

  async register(input: { email: string; password: string; display_name: string; phone: string }) {
    const response = await fetch("/api/retail/auth/register", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    });
    if (!response.ok) throw await this.error(response, "Could not create account");
    return userSchema.parse((await response.json()).user);
  }

  async login(email: string, password: string) {
    const response = await fetch("/api/retail/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }),
    });
    if (!response.ok) throw await this.error(response, "Sign in failed");
    const value = sessionSchema.parse(await response.json());
    this.csrf = value.csrf;
    return value.user;
  }

  async logout() {
    const response = await fetch("/api/retail/auth/logout", {
      method: "POST", headers: this.mutationHeaders(), body: "{}",
    });
    if (!response.ok) throw await this.error(response, "Sign out failed");
    this.csrf = "";
  }

  async products() {
    const response = await fetch("/api/retail/products");
    if (!response.ok) throw await this.error(response, "Could not load products");
    return productsSchema.parse(await response.json()).items;
  }

  async cart() {
    const response = await fetch("/api/retail/cart");
    if (!response.ok) throw await this.error(response, "Could not load cart");
    return cartSchema.parse(await response.json());
  }

  async setCartItem(productId: string, quantity: number) {
    const response = await fetch("/api/retail/cart/items", {
      method: "POST", headers: this.mutationHeaders(),
      body: JSON.stringify({ product_id: productId, quantity }),
    });
    if (!response.ok) throw await this.error(response, "Could not update cart");
    return cartSchema.parse(await response.json());
  }

  async updateCartItem(productId: string, quantity: number) {
    const response = await fetch(`/api/retail/cart/items/${encodeURIComponent(productId)}`, {
      method: "PATCH", headers: this.mutationHeaders(), body: JSON.stringify({ quantity }),
    });
    if (!response.ok) throw await this.error(response, "Could not update quantity");
    return cartSchema.parse(await response.json());
  }

  async removeCartItem(productId: string) {
    const response = await fetch(`/api/retail/cart/items/${encodeURIComponent(productId)}`, {
      method: "DELETE", headers: this.mutationHeaders(), body: "{}",
    });
    if (!response.ok) throw await this.error(response, "Could not remove item");
    return cartSchema.parse(await response.json());
  }

  async checkout(address: Record<string, string>, key: string) {
    const response = await fetch("/api/retail/checkout", {
      method: "POST", headers: this.mutationHeaders(key), body: JSON.stringify(address),
    });
    if (!response.ok) throw await this.error(response, "Checkout failed");
    return orderSchema.parse(await response.json());
  }

  async orders() {
    const response = await fetch("/api/retail/orders");
    if (!response.ok) throw await this.error(response, "Could not load orders");
    return ordersSchema.parse(await response.json()).items;
  }

  async order(id: string) {
    const response = await fetch(`/api/retail/orders/${encodeURIComponent(id)}`);
    if (!response.ok) throw await this.error(response, "Order not found");
    return orderSchema.parse(await response.json());
  }
}
