/* Which surface this page is, from the URL alone:
     /                 home
     /start            create your own shop (self-service signup)
     /admin            provider console        /lab   attack testbed
     /{slug}/shop      a shop's storefront     /{slug}/admin   that shop's owner admin
   Shops are data: any slug is a shop, and its look comes from /api/mall/shops/{slug}. */

export type ShopId = string;
export type ShopTheme = "navy" | "forest" | "plum" | "sunset" | "graphite";

export interface ShopConfig {
  id: ShopId;
  name: string;
  legal: string;
  initial: string;
  api: string;
  base: string;
  eyebrow: string;
  heroTitle: string;
  heroText: string;
  theme: ShopTheme;
  categories: string[];
  categoryByCode: Record<string, string>;
  /** Testbed shops (Northstar, Bloom) ship sample data; template shops start empty. */
  fixed: boolean;
}

/** Public shop record from /api/mall/shops. */
export interface MallShop {
  slug: string;
  name: string;
  tagline: string;
  hero_title: string;
  hero_text: string;
  theme: ShopTheme;
  categories: Array<{ code: string; name: string }>;
  fixed: boolean;
  state: "live" | "provisioning" | "failed";
}

const NON_SHOP = new Set(["admin", "lab", "start", "api"]);

type Surface =
  | { kind: "shop"; view: "shop" | "admin"; slug: string }
  | { kind: "provider" } | { kind: "lab" } | { kind: "create" } | { kind: "home" };

function detect(): Surface {
  const [first, second] = window.location.pathname.split("/").filter(Boolean);
  if (first === "admin") return { kind: "provider" };
  if (first === "lab") return { kind: "lab" };  // attack testbed, kept apart from the production console
  if (first === "start") return { kind: "create" };
  if (first && !NON_SHOP.has(first) && /^[a-z][a-z0-9-]{2,23}$/.test(first)) {
    return { kind: "shop", view: second === "admin" ? "admin" : "shop", slug: first };
  }
  return { kind: "home" };
}

export const SURFACE = detect();
/** The testbed signs in with the provider account and uses the provider API. */
export const IS_LAB = SURFACE.kind === "lab";
export const IS_PROVIDER = SURFACE.kind === "provider" || IS_LAB;

const slug = SURFACE.kind === "shop" ? SURFACE.slug : "northstar";

/** The current shop. API path and URL come from the slug; display fields arrive from loadShop(). */
export const SHOP: ShopConfig = {
  id: slug, name: slug, legal: slug, initial: slug[0]?.toUpperCase() ?? "S", api: `/api/shops/${slug}`, base: `/${slug}`,
  eyebrow: "", heroTitle: "", heroText: "", theme: "navy", categories: [], categoryByCode: {}, fixed: false,
};
export const SHOP_BASE = `${SHOP.base}/shop`;
export const ADMIN_API = IS_PROVIDER ? "/api/provider" : SHOP.api;
export const ADMIN_BASE = IS_LAB ? "/lab" : IS_PROVIDER ? "/admin" : `${SHOP.base}/admin`;
/** Accounts are shared by every shop, so any shop's auth endpoints sign you in everywhere. */
export const ACCOUNTS_API = "/api/shops/northstar";

export function applyShop(shop: MallShop) {
  Object.assign(SHOP, {
    id: shop.slug, name: shop.name, legal: shop.name, initial: shop.name.trim()[0]?.toUpperCase() ?? "S",
    eyebrow: shop.tagline, heroTitle: shop.hero_title, heroText: shop.hero_text, theme: shop.theme, fixed: shop.fixed,
    categories: shop.categories.map((item) => item.name),
    categoryByCode: Object.fromEntries(shop.categories.map((item) => [item.code, item.name])),
  });
}

/** Load the current shop's look before its app renders. Resolves to the shop, or null if there is none. */
export async function loadShop(): Promise<MallShop | null> {
  if (SURFACE.kind !== "shop") return null;
  const response = await fetch(`/api/mall/shops/${encodeURIComponent(SURFACE.slug)}`).catch(() => null);
  if (!response?.ok) return null;
  const shop = (await response.json()) as MallShop;
  applyShop(shop);
  return shop;
}

export async function listShops(): Promise<{ items: MallShop[]; quota: { used: number; limit: number } }> {
  const response = await fetch("/api/mall/shops");
  if (!response.ok) throw new Error("Could not load shops");
  return response.json();
}

export const THEMES: Array<{ id: ShopTheme; name: string; accent: string; soft: string }> = [
  { id: "navy", name: "Navy", accent: "#1e2d55", soft: "#e8ecf5" },
  { id: "forest", name: "Forest", accent: "#1f5135", soft: "#e4f0e8" },
  { id: "plum", name: "Plum", accent: "#5b2a6e", soft: "#f1e7f5" },
  { id: "sunset", name: "Sunset", accent: "#a13d12", soft: "#fbeae0" },
  { id: "graphite", name: "Graphite", accent: "#2b2f36", soft: "#eceef1" },
];
