import { lazy, StrictMode, Suspense, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import Loader from "./components/kokonutui/loader";
import { loadShop, SURFACE } from "./shop";
import "./app.css";

const StorefrontApp = lazy(() => import("./storefront/StorefrontApp"));
const AdminApp = lazy(() => import("./admin/AdminApp"));
const Home = lazy(() => import("./home/Home"));
const CreateShop = lazy(() => import("./create/CreateShop"));

const root = createRoot(document.getElementById("root")!);
const loading = (title: string, subtitle: string) => <main className="route-loader"><Loader size="sm" title={title} subtitle={subtitle} /></main>;
const render = (node: ReactNode, fallback: ReactNode) => root.render(<StrictMode><Suspense fallback={fallback}>{node}</Suspense></StrictMode>);

function NoShop() {
  return (
    <main className="route-loader" style={{ textAlign: "center", gap: "0.75rem" }}>
      <h1 style={{ fontSize: "1.6rem", margin: 0 }}>There is no shop here.</h1>
      <p style={{ margin: 0, color: "#5d6b82" }}>Check the address, or open a shop of your own.</p>
      <p style={{ margin: 0 }}><a href="/">Home</a> · <a href="/start">Open a shop</a></p>
    </main>
  );
}

async function start() {
  if (SURFACE.kind === "home") return render(<Home />, loading("Loading SecureCloud", "Zero-trust security for multi-tenant clusters"));
  if (SURFACE.kind === "create") return render(<CreateShop />, loading("Opening", "Create your shop"));
  if (SURFACE.kind === "provider" || SURFACE.kind === "lab") return render(<AdminApp />, loading("Opening administration", "Checking your session"));
  root.render(loading("Opening the shop", "Loading its catalogue and look"));
  const shop = await loadShop();
  if (!shop) return root.render(<StrictMode><NoShop /></StrictMode>);
  if (SURFACE.view === "admin") return render(<AdminApp />, loading("Opening administration", "Checking your session"));
  return render(<StorefrontApp />, loading("Opening storefront", "Loading your account and catalogue"));
}

void start();
