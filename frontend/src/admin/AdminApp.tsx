import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Activity, Database, ExternalLink, FlaskConical, LayoutDashboard, Menu, Package, ShieldAlert, ShieldCheck, ShoppingBag, User, Users, X } from "lucide-react";
import ActionSearchBar, { type CommandItem } from "../components/kokonutui/action-search-bar";
import Loader from "../components/kokonutui/loader";
import ProfileDropdown from "../components/kokonutui/profile-dropdown";
import { Toaster, usePromiseToast } from "../components/kokonutui/promise-toast";
import { ToasterContext, errorText } from "./toast";
import { AdminService, type AdminSnapshot, type RetailUser } from "./adminService";
import { Dashboard } from "./pages/Dashboard";
import { Orders } from "./pages/Orders";
import { Customers } from "./pages/Customers";
import { Products } from "./pages/Products";
import { Security } from "./pages/Security";
import { Services } from "./pages/Services";
import { Lab } from "./pages/Lab";
import "./admin.css";
import { ADMIN_BASE, IS_PROVIDER, SHOP } from "../shop";

const BRAND = IS_PROVIDER
  ? { initial: "S", name: "SecureCloud", tagline: "Provider console" }
  : { initial: SHOP.initial, name: SHOP.name, tagline: "Store administration" };
const STOREFRONT = `${SHOP.base}/shop`;

export type AdminPage = "overview" | "orders" | "customers" | "products" | "lab" | "security" | "services";

const ALL_PAGES: Array<{ id: AdminPage; label: string; icon: typeof LayoutDashboard; group: "Store" | "SecureCloud" }> = [
  { id: "overview", label: "Overview", icon: LayoutDashboard, group: "Store" },
  { id: "orders", label: "Orders", icon: ShoppingBag, group: "Store" },
  { id: "customers", label: "Customers", icon: Users, group: "Store" },
  { id: "products", label: "Products", icon: Package, group: "Store" },
  { id: "lab", label: "Live lab", icon: FlaskConical, group: "SecureCloud" },
  { id: "security", label: "Security activity", icon: ShieldAlert, group: "SecureCloud" },
  { id: "services", label: "Shared services & plugins", icon: Activity, group: "SecureCloud" },
];
const PAGES = ALL_PAGES.filter((item) => (item.group === "SecureCloud") === IS_PROVIDER);

function locationState(): { page: AdminPage; id: string | null } {
  const [first, second] = window.location.pathname.slice(ADMIN_BASE.length).replace(/^\//, "").split("/");
  const page = PAGES.some((item) => item.id === first) ? first as AdminPage : PAGES[0].id;
  return { page, id: page === "orders" && second ? decodeURIComponent(second) : null };
}

export default function AdminApp() {
  const service = useMemo(() => new AdminService(), []);
  const [owner, setOwner] = useState<RetailUser | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    document.title = `${BRAND.name} · ${BRAND.tagline}`;
    void service.session().then(setOwner)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Admin is unavailable"))
      .finally(() => setChecking(false));
  }, [service]);

  if (checking) return <main className="route-loader"><Loader size="sm" title="Opening administration" subtitle="Checking your owner session" /></main>;
  if (!owner) return <OwnerLogin service={service} initialError={error} onSuccess={setOwner} />;
  return <AdminShell service={service} owner={owner} onLogout={() => setOwner(null)} />;
}

function OwnerLogin({ service, initialError, onSuccess }: { service: AdminService; initialError: string; onSuccess: (user: RetailUser) => void }) {
  const [error, setError] = useState(initialError);
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const data = new FormData(event.currentTarget);
    try { onSuccess(await service.login(String(data.get("email")), String(data.get("password")))); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Sign in failed"); }
    finally { setBusy(false); }
  }
  return (
    <main className="ad-login">
      <section className="ad-login-card">
        <div className="ad-brand ad-brand-dark"><span className="ad-brand-mark">{BRAND.initial}</span><span><strong>{BRAND.name}</strong><small>{BRAND.tagline}</small></span></div>
        <h1>{IS_PROVIDER ? "Sign in to the provider console" : "Sign in to your store"}</h1>
        <p>{IS_PROVIDER ? "Service map, live lab, incidents, shared services and plugins for every shop on the platform." : "Orders, customers and products for your shop. One SecureCloud Mall account works everywhere."}</p>
        <form className="ad-form" onSubmit={(event) => void submit(event)}>
          <label>Email<input name="email" type="email" required autoComplete="email" /></label>
          <label>Password<input name="password" type="password" required autoComplete="current-password" /></label>
          {error && <p className="ad-inline-error" role="alert">{error}</p>}
          <button className="ad-button ad-button-primary ad-button-block" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
        {!IS_PROVIDER && <a className="ad-login-back" href={STOREFRONT}>← Back to storefront</a>}
      </section>
      <aside className="ad-login-art" aria-hidden="true">
        <div className="ad-login-art-inner">
          <ShieldCheck size={40} strokeWidth={1.5} />
          <h2>Every service isolated. Every connection verified.</h2>
          <p>SecureCloud enforces default-deny network policy between the storefront, order and payment services, scores traffic with a temporal-graph model, and lets you quarantine a compromised workload.</p>
          <ul>
            <li><span />Default-deny Cilium policies</li>
            <li><span />Hubble flow telemetry</li>
            <li><span />Verified quarantine and restore</li>
          </ul>
        </div>
      </aside>
    </main>
  );
}

function AdminShell({ service, owner, onLogout }: { service: AdminService; owner: RetailUser; onLogout: () => void }) {
  const [{ page, id }, setLocation] = useState(locationState);
  const [data, setData] = useState<AdminSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [menu, setMenu] = useState(false);
  const [query, setQuery] = useState("");
  const [loadingSample, setLoadingSample] = useState(false);
  const toaster = usePromiseToast();

  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try { setData(await service.snapshot()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Admin data could not be loaded"); }
    finally { setLoading(false); }
  }, [service]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const pop = () => setLocation(locationState());
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => {
    if (!data || !IS_PROVIDER) return;
    let active = true;
    const timer = window.setInterval(() => {
      void service.securitySummary()
        .then((security) => { if (active) setData((current) => current ? { ...current, security } : current); })
        .catch(() => undefined);
    }, page === "security" ? 5_000 : 20_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [data !== null, page, service]);

  function navigate(next: AdminPage, nextId: string | null = null) {
    const path = next === PAGES[0].id ? ADMIN_BASE : `${ADMIN_BASE}/${next}${nextId ? `/${encodeURIComponent(nextId)}` : ""}`;
    window.history.pushState({}, "", path);
    setLocation({ page: next, id: nextId });
    setMenu(false);
    if (next !== page) setQuery("");
  }
  async function logout() { await service.logout(); onLogout(); }
  async function loadSample() {
    setLoadingSample(true);
    toaster.show(async () => {
      try {
        const result = await service.loadDemoCatalog();
        await refresh();
        return result;
      } finally { setLoadingSample(false); }
    }, {
      loading: "Loading sample data",
      waiting: "Catalogue and labelled sample orders",
      success: (result) => result.sample_orders
        ? [`Loaded ${result.sample_orders} sample orders`, `${result.items.length} products in the catalogue`]
        : ["Catalogue refreshed", "Sample orders were already loaded"],
      error: (reason) => ["Could not load sample data", errorText(reason, "Try again")],
    });
  }

  const openIncidents = data?.security.incidents.filter((incident) => incident.status !== "restored" && incident.status !== "closed").length ?? 0;
  const openOrders = data?.orders.filter((order) => order.status === "placed" || order.status === "processing").length ?? 0;
  const current = PAGES.find((item) => item.id === page)!;
  const commands = useMemo<CommandItem[]>(() => {
    if (!data) return [];
    return [
      ...PAGES.map((item) => { const Icon = item.icon; return { id: `page:${item.id}`, label: item.label, group: "Go to", icon: <Icon size={16} />, keywords: [item.group] }; }),
      { id: "group:orders", label: "Find an order", group: "Search", icon: <ShoppingBag size={16} />, placeholder: "Order number, customer or city",
        children: data.orders.slice(0, 200).map((order) => ({ id: `order:${order.id}`, label: `${order.order_number} · ${order.customer.name}`, keywords: [order.customer.email, order.delivery_address.city, order.status] })) },
      { id: "group:customers", label: "Find a customer", group: "Search", icon: <User size={16} />, placeholder: "Name or email",
        children: data.customers.map((customer) => ({ id: `customer:${customer.display_name}`, label: customer.display_name, keywords: [customer.email] })) },
      { id: "group:products", label: "Find a product", group: "Search", icon: <Package size={16} />, placeholder: "Name or SKU",
        children: data.products.map((product) => ({ id: `product:${product.name}`, label: product.name, keywords: [product.sku] })) },
      { id: "action:sample", label: "Load sample data", group: "Actions", icon: <Database size={16} /> },
      ...(IS_PROVIDER ? [] : [{ id: "action:storefront", label: "Open storefront", group: "Actions", icon: <ExternalLink size={16} />, href: STOREFRONT }]),
    ];
  }, [data]);
  function runCommand(item: CommandItem) {
    const [kind, ...rest] = item.id.split(":");
    const value = rest.join(":");
    if (kind === "page") navigate(value as AdminPage);
    if (kind === "order") navigate("orders", value);
    if (kind === "customer") { navigate("customers"); setQuery(value); }
    if (kind === "product") { navigate("products"); setQuery(value); }
    if (kind === "action" && value === "sample") return loadSample();
    if (kind === "action" && value === "storefront") window.open(STOREFRONT, "_blank", "noreferrer");
  }

  return (
    <ToasterContext.Provider value={toaster}>
    <div className="ad-app">
      <aside className={`ad-sidebar ${menu ? "open" : ""}`}>
        <a className="ad-brand" href={ADMIN_BASE}><span className="ad-brand-mark">{BRAND.initial}</span><span><strong>{BRAND.name}</strong><small>{BRAND.tagline}</small></span></a>
        {(IS_PROVIDER ? ["SecureCloud"] as const : ["Store"] as const).map((group) => (
          <div key={group} className="ad-nav-group">
            <p>{group}</p>
            <nav aria-label={group === "Store" ? "Admin navigation" : "SecureCloud navigation"}>
              {PAGES.filter((item) => item.group === group).map((item) => {
                const Icon = item.icon;
                const badge = item.id === "orders" ? openOrders : item.id === "security" ? openIncidents : 0;
                return (
                  <button key={item.id} className={page === item.id ? "active" : ""} aria-current={page === item.id ? "page" : undefined} onClick={() => navigate(item.id)}>
                    <Icon size={17} aria-hidden="true" /><span>{item.label}</span>
                    {badge > 0 && <b className={item.id === "security" ? "alert" : ""}>{badge}</b>}
                  </button>
                );
              })}
            </nav>
          </div>
        ))}
        {!IS_PROVIDER && <a className="ad-nav-external" href={STOREFRONT} target="_blank" rel="noreferrer"><ExternalLink size={16} aria-hidden="true" />View storefront</a>}
        <div className="ad-sidebar-status">
          <span className={`ad-pulse ${data?.apiOnline ? "on" : "off"}`} aria-hidden="true" />
          <div><strong>{data?.apiOnline ? (IS_PROVIDER ? "Platform online" : "Protected by SecureCloud") : "Status unavailable"}</strong><small>{IS_PROVIDER ? (openIncidents ? `${openIncidents} open incident${openIncidents === 1 ? "" : "s"}` : "No open incidents") : "Security is managed by your platform provider"}</small></div>
        </div>
      </aside>
      {menu && <button className="ad-sidebar-scrim" aria-label="Close navigation" onClick={() => setMenu(false)} />}
      <div className="ad-content">
        <header className="ad-topbar">
          <button className="ad-icon-button ad-menu" onClick={() => setMenu((value) => !value)} aria-label="Toggle admin navigation">{menu ? <X size={18} /> : <Menu size={18} />}</button>
          <div className="ad-crumb"><span>{BRAND.name}</span><span aria-hidden="true">/</span><strong>{current.label}</strong></div>
          <ActionSearchBar className="ad-command" items={commands} defaultRecent={IS_PROVIDER ? ["page:lab", "page:security"] : ["page:orders", "page:products"]}
            onSelect={(item) => runCommand(item)} shortcut label="Search admin" placeholder={IS_PROVIDER ? "Go to a page…" : "Search orders, customers, products…"} />
          <div className="ad-topbar-end">
            <ProfileDropdown compact showPreferences={false}
              accounts={[{ id: owner.id, name: owner.display_name, email: owner.email, plan: IS_PROVIDER ? "Provider" : "Owner" }]}
              items={IS_PROVIDER ? [] : [{ label: "Storefront", href: STOREFRONT, icon: <ShoppingBag className="size-4" /> }]}
              onSignOut={() => void logout()} />
          </div>
        </header>
        <main className="ad-main">
          {error && <div className="ad-banner" role="alert"><strong>Could not refresh the dashboard.</strong><span>{error}</span><button className="ad-button" onClick={() => void refresh()}>Try again</button></div>}
          {loading && !data
            ? <div className="ad-loading"><Loader size="sm" title="Loading store operations" subtitle="Orders, customers, services and security" /></div>
            : data && (
              <>
                {page === "overview" && <Dashboard data={data} navigate={(next, nextId) => navigate(next, nextId ?? null)} refresh={refresh} onLoadSample={loadSample} loadingSample={loadingSample} />}
                {page === "orders" && <Orders data={data} service={service} query={query} setQuery={setQuery} refresh={refresh} selectedId={id} select={(next) => navigate("orders", next)} />}
                {page === "customers" && <Customers data={data} query={query} setQuery={setQuery} openOrder={(orderId) => navigate("orders", orderId)} />}
                {page === "products" && <Products data={data} service={service} query={query} setQuery={setQuery} refresh={refresh} onLoadSample={loadSample} loadingSample={loadingSample} />}
                {page === "lab" && <Lab data={data} service={service} refresh={refresh} />}
                {page === "security" && <Security data={data} service={service} refresh={refresh} />}
                {page === "services" && <Services service={service} />}
              </>
            )}
        </main>
      </div>
      <Toaster toaster={toaster} className="ad-toaster" />
    </div>
    </ToasterContext.Provider>
  );
}
