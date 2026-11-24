import type { Order, Product } from "./adminService";

export type DayPoint = { date: Date; key: string; revenue: number; orders: number };

const DAY = 86400;

function dayKey(date: Date) {
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

function startOfDay(seconds: number) {
  const date = new Date(seconds * 1000);
  date.setHours(0, 0, 0, 0);
  return date;
}

const counts = (order: Order) => order.status !== "cancelled";

/** Daily revenue and orders for the `days` days ending today (local time). */
export function dailySeries(orders: Order[], days: number, endSeconds = Date.now() / 1000): DayPoint[] {
  const end = startOfDay(endSeconds);
  const points: DayPoint[] = [];
  const index = new Map<string, DayPoint>();
  for (let offset = days - 1; offset >= 0; offset--) {
    const date = new Date(end);
    date.setDate(end.getDate() - offset);
    const point = { date, key: dayKey(date), revenue: 0, orders: 0 };
    points.push(point);
    index.set(point.key, point);
  }
  for (const order of orders) {
    if (!counts(order)) continue;
    const point = index.get(dayKey(new Date(order.created_at * 1000)));
    if (point) { point.revenue += order.total_minor; point.orders += 1; }
  }
  return points;
}

export type PeriodSummary = { revenue: number; orders: number; aov: number; customers: number };

function summarize(orders: Order[], from: number, to: number): PeriodSummary {
  const inRange = orders.filter((order) => counts(order) && order.created_at >= from && order.created_at < to);
  const revenue = inRange.reduce((sum, order) => sum + order.total_minor, 0);
  return {
    revenue,
    orders: inRange.length,
    aov: inRange.length ? Math.round(revenue / inRange.length) : 0,
    customers: new Set(inRange.map((order) => order.user_id)).size,
  };
}

export function periodComparison(orders: Order[], days: number, nowSeconds = Date.now() / 1000) {
  const startCurrent = startOfDay(nowSeconds).getTime() / 1000 - (days - 1) * DAY;
  const current = summarize(orders, startCurrent, nowSeconds + 1);
  const previous = summarize(orders, startCurrent - days * DAY, startCurrent);
  return { current, previous };
}

export function delta(current: number, previous: number) {
  if (!previous) return current ? null : 0;
  return (current - previous) / previous;
}

export function topProducts(orders: Order[], products: Product[], days: number, nowSeconds = Date.now() / 1000) {
  const from = startOfDay(nowSeconds).getTime() / 1000 - (days - 1) * DAY;
  const totals = new Map<string, { id: string; name: string; units: number; revenue: number }>();
  for (const order of orders) {
    if (!counts(order) || order.created_at < from) continue;
    for (const item of order.items) {
      const entry = totals.get(item.product_id) ?? { id: item.product_id, name: item.name_snapshot, units: 0, revenue: 0 };
      entry.units += item.quantity;
      entry.revenue += item.unit_price_minor * item.quantity;
      totals.set(item.product_id, entry);
    }
  }
  const images = new Map(products.map((product) => [product.id, product.image_path]));
  return [...totals.values()].sort((a, b) => b.revenue - a.revenue).map((entry) => ({ ...entry, image: images.get(entry.id) ?? "" }));
}

export const STATUS_ORDER: Order["status"][] = ["placed", "processing", "packing", "shipped", "delivered", "cancelled"];

export const STATUS_LABEL: Record<Order["status"], string> = {
  placed: "Placed", processing: "Processing", packing: "Packed", shipped: "Shipped", delivered: "Delivered", cancelled: "Cancelled",
};

export function statusCounts(orders: Order[]) {
  const result = Object.fromEntries(STATUS_ORDER.map((status) => [status, 0])) as Record<Order["status"], number>;
  for (const order of orders) result[order.status] += 1;
  return result;
}

export const NEXT_STATUS: Record<Order["status"], Order["status"][]> = {
  placed: ["processing", "cancelled"], processing: ["packing", "cancelled"], packing: ["shipped"],
  shipped: ["delivered"], delivered: [], cancelled: [],
};

export const CATEGORIES = ["Bags", "Accessories", "Home"] as const;
const CATEGORY_BY_CODE: Record<string, (typeof CATEGORIES)[number]> = { BAG: "Bags", ACC: "Accessories", HOM: "Home" };

export function categoryOfSku(sku: string) {
  return CATEGORY_BY_CODE[sku.split("-")[1] ?? ""] ?? "Accessories";
}

const isoDay = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

/** Daily revenue in rupees split by storefront category, oldest first, for MetricCard. */
export function categoryRevenueSeries(orders: Order[], days: number, endSeconds = Date.now() / 1000) {
  const end = startOfDay(endSeconds);
  const points: Array<{ date: string; parts: number[] }> = [];
  const index = new Map<string, number[]>();
  for (let offset = days - 1; offset >= 0; offset--) {
    const date = new Date(end);
    date.setDate(end.getDate() - offset);
    const parts = CATEGORIES.map(() => 0);
    points.push({ date: isoDay(date), parts });
    index.set(isoDay(date), parts);
  }
  for (const order of orders) {
    if (!counts(order)) continue;
    const parts = index.get(isoDay(new Date(order.created_at * 1000)));
    if (!parts) continue;
    for (const item of order.items) {
      parts[CATEGORIES.indexOf(categoryOfSku(item.sku_snapshot))] += (item.unit_price_minor * item.quantity) / 100;
    }
  }
  return points;
}

export function dayOf(seconds: number) {
  return isoDay(new Date(seconds * 1000));
}
