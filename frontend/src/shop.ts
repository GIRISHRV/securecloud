/* Which surface this page is: a shop's storefront/admin, the provider console, or the home page.
   /northstar/shop · /northstar/admin · /bloom/shop · /bloom/admin · /admin (provider) */
export type ShopId = "northstar" | "bloom";

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
  categories: string[];
  categoryByCode: Record<string, string>;
}

export const SHOPS: Record<ShopId, ShopConfig> = {
  northstar: {
    id: "northstar", name: "Northstar", legal: "Northstar Retail", initial: "N", api: "/api/retail", base: "/northstar",
    eyebrow: "New season · Everyday carry", heroTitle: "Everyday goods, built to last.",
    heroText: "Bags, bottles, lamps and eyewear chosen for daily use. Fast delivery and easy returns across India.",
    categories: ["Bags", "Accessories", "Home"], categoryByCode: { BAG: "Bags", ACC: "Accessories", HOM: "Home" },
  },
  bloom: {
    id: "bloom", name: "Bloom", legal: "Bloom Candle Co.", initial: "B", api: "/api/bloom", base: "/bloom",
    eyebrow: "Hand-poured in Bengaluru", heroTitle: "Slow evenings, softly lit.",
    heroText: "Soy candles, reed diffusers and gift boxes in scents inspired by Indian gardens and kitchens.",
    categories: ["Candles", "Diffusers", "Gift sets"], categoryByCode: { CAN: "Candles", DIF: "Diffusers", GFT: "Gift sets" },
  },
};

type Surface = { kind: "shop"; view: "shop" | "admin"; shop: ShopConfig } | { kind: "provider" } | { kind: "home" };

function detect(): Surface {
  const [first, second] = window.location.pathname.split("/").filter(Boolean);
  if (first === "admin") return { kind: "provider" };
  if (first === "northstar" || first === "bloom") return { kind: "shop", view: second === "admin" ? "admin" : "shop", shop: SHOPS[first] };
  return { kind: "home" };
}

export const SURFACE = detect();
export const IS_PROVIDER = SURFACE.kind === "provider";
export const SHOP: ShopConfig = SURFACE.kind === "shop" ? SURFACE.shop : SHOPS.northstar;
export const SHOP_BASE = `${SHOP.base}/shop`;
export const ADMIN_API = IS_PROVIDER ? "/api/provider" : SHOP.api;
export const ADMIN_BASE = IS_PROVIDER ? "/admin" : `${SHOP.base}/admin`;
