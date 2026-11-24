import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import Loader from "./components/kokonutui/loader";
import "./app.css";

const StorefrontApp = lazy(() => import("./storefront/StorefrontApp"));
const AdminApp = lazy(() => import("./admin/AdminApp"));
const isAdmin = window.location.pathname === "/admin" || window.location.pathname.startsWith("/admin/");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {isAdmin ? (
      <Suspense fallback={<main className="route-loader"><Loader size="sm" title="Opening administration" subtitle="Loading business and security controls" /></main>}>
        <AdminApp />
      </Suspense>
    ) : (
      <Suspense fallback={<main className="route-loader"><Loader size="sm" title="Opening storefront" subtitle="Loading your account and catalogue" /></main>}>
        <StorefrontApp />
      </Suspense>
    )}
  </StrictMode>,
);
