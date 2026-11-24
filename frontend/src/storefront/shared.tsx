import type { ReactNode } from "react";
import type { Order, Product } from "./retailService";

export type Route =
  | { name: "home"; category?: string }
  | { name: "product"; id: string }
  | { name: "cart" }
  | { name: "checkout" }
  | { name: "orders" }
  | { name: "order"; id: string }
  | { name: "login" }
  | { name: "register" };

export type Navigate = (route: Route) => void;

export const money = (minor: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(minor / 100);

export const dateTime = (seconds: number) =>
  new Date(seconds * 1000).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });

export const dateOnly = (seconds: number) =>
  new Date(seconds * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

const CATEGORY_BY_CODE: Record<string, string> = { BAG: "Bags", ACC: "Accessories", HOM: "Home" };

export function categoryOf(product: Pick<Product, "sku">) {
  const code = product.sku.split("-")[1] ?? "";
  return CATEGORY_BY_CODE[code] ?? "Other";
}

export function routeFromPath(): Route {
  const path = window.location.pathname.replace(/^\/shop\/?/, "").split("/").filter(Boolean);
  const category = new URLSearchParams(window.location.search).get("category") ?? undefined;
  if (!path.length) return { name: "home", category };
  if (path[0] === "products" && path[1]) return { name: "product", id: decodeURIComponent(path[1]) };
  if (path[0] === "cart") return { name: "cart" };
  if (path[0] === "checkout") return { name: "checkout" };
  if (path[0] === "account" && path[1] === "orders" && path[2]) return { name: "order", id: decodeURIComponent(path[2]) };
  if (path[0] === "account" && path[1] === "orders") return { name: "orders" };
  if (path[0] === "login") return { name: "login" };
  if (path[0] === "register") return { name: "register" };
  return { name: "home" };
}

export function pathFor(route: Route) {
  if (route.name === "home") return route.category ? `/shop?category=${encodeURIComponent(route.category)}` : "/shop";
  if (route.name === "product") return `/shop/products/${encodeURIComponent(route.id)}`;
  if (route.name === "orders") return "/shop/account/orders";
  if (route.name === "order") return `/shop/account/orders/${encodeURIComponent(route.id)}`;
  return `/shop/${route.name}`;
}

export function Link({ route, navigate, children, className = "", ariaLabel }: {
  route: Route; navigate: Navigate; children: ReactNode; className?: string; ariaLabel?: string;
}) {
  return (
    <a className={className} href={pathFor(route)} aria-label={ariaLabel}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey) return;
        event.preventDefault();
        navigate(route);
      }}>
      {children}
    </a>
  );
}

export function ProductImage({ src, name }: { src?: string; name: string }) {
  return src
    ? <img src={src} alt={name} loading="lazy" />
    : <span className="sf-image-fallback" aria-hidden="true">{name.slice(0, 1)}</span>;
}

export const ORDER_STEPS: Array<{ status: Order["status"]; label: string; detail: string }> = [
  { status: "placed", label: "Order placed", detail: "Payment confirmed" },
  { status: "processing", label: "Processing", detail: "Preparing your items" },
  { status: "packing", label: "Packed", detail: "Ready for dispatch" },
  { status: "shipped", label: "Shipped", detail: "On the way to you" },
  { status: "delivered", label: "Delivered", detail: "Handed over" },
];

export const STATUS_LABEL: Record<Order["status"], string> = {
  placed: "Placed", processing: "Processing", packing: "Packed",
  shipped: "Shipped", delivered: "Delivered", cancelled: "Cancelled",
};

export function OrderStatus({ status }: { status: Order["status"] }) {
  return <span className={`sf-status sf-status-${status}`}>{STATUS_LABEL[status]}</span>;
}

export function stockNote(stock: number) {
  if (stock === 0) return { tone: "out", text: "Out of stock" };
  if (stock <= 10) return { tone: "low", text: `Only ${stock} left` };
  return { tone: "in", text: "In stock" };
}
