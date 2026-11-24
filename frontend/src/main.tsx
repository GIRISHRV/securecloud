import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import Loader from "./components/kokonutui/loader";
import { SHOPS, SURFACE } from "./shop";
import "./app.css";

const StorefrontApp = lazy(() => import("./storefront/StorefrontApp"));
const AdminApp = lazy(() => import("./admin/AdminApp"));

function Home() {
  const links = [
    ...Object.values(SHOPS).flatMap((shop) => [
      { href: `${shop.base}/shop`, title: `${shop.name} storefront`, text: `Shop ${shop.categories.join(", ").toLowerCase()}` },
      { href: `${shop.base}/admin`, title: `${shop.name} admin`, text: "Orders, products and customers for this shop" },
    ]),
    { href: "/admin", title: "SecureCloud provider console", text: "Service map, live lab, incidents, shared services and plugins" },
  ];
  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "48px 16px", fontFamily: "Inter, system-ui, sans-serif" }}>
      <h1 style={{ fontSize: 28, marginBottom: 4 }}>SecureCloud Mall</h1>
      <p style={{ color: "#5b6472", marginBottom: 24 }}>Two independent shops on one platform, protected by the provider.</p>
      <div style={{ display: "grid", gap: 12 }}>
        {links.map((link) => (
          <a key={link.href} href={link.href} style={{ display: "block", padding: "14px 16px", border: "1px solid #e3e7ee", borderRadius: 12, color: "inherit", textDecoration: "none" }}>
            <strong>{link.title}</strong>
            <div style={{ color: "#5b6472", fontSize: 14 }}>{link.text} · <code>{link.href}</code></div>
          </a>
        ))}
      </div>
    </main>
  );
}

const admin = SURFACE.kind === "provider" || (SURFACE.kind === "shop" && SURFACE.view === "admin");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {SURFACE.kind === "home" ? <Home /> : admin ? (
      <Suspense fallback={<main className="route-loader"><Loader size="sm" title="Opening administration" subtitle="Checking your session" /></main>}>
        <AdminApp />
      </Suspense>
    ) : (
      <Suspense fallback={<main className="route-loader"><Loader size="sm" title="Opening storefront" subtitle="Loading your account and catalogue" /></main>}>
        <StorefrontApp />
      </Suspense>
    )}
  </StrictMode>,
);
