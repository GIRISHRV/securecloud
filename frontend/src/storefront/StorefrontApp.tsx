import { useEffect, useState } from "react";
import { Search, ShieldCheck, ShoppingBag, Menu, X } from "lucide-react";
import Loader from "../components/kokonutui/loader";
import ProfileDropdown from "../components/kokonutui/profile-dropdown";
import { RetailProvider, useRetail } from "./RetailContext";
import { Link, pathFor, routeFromPath, type Route } from "./shared";
import {
  AuthLogin, AuthRegister, CartPage, CheckoutPage, HomePage, OrderPage, OrdersPage, ProductPage, StoreMessage,
} from "./pages";
import "./storefront.css";
import { SHOP, SHOP_BASE } from "../shop";

export default function StorefrontApp() {
  return <RetailProvider><Storefront /></RetailProvider>;
}

const CATEGORIES = SHOP.categories;

function Storefront() {
  const { user, cart, loading, error, service, acceptUser } = useRetail();
  const [route, setRoute] = useState<Route>(routeFromPath);
  const [menuOpen, setMenuOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const pop = () => setRoute(routeFromPath());
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => { document.title = `${SHOP.name} · ${SHOP.eyebrow}`; }, []);

  function navigate(next: Route) {
    window.history.pushState({}, "", pathFor(next));
    setRoute(next);
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  async function logout() {
    await service.logout();
    await acceptUser(null);
    navigate({ name: "home" });
  }
  function search(value: string) {
    setQuery(value);
    if (route.name !== "home") navigate({ name: "home" });
  }

  const count = cart?.items.reduce((total, item) => total + item.quantity, 0) ?? 0;
  const activeCategory = route.name === "home" ? route.category : undefined;

  return (
    <div className="sf">
      <a className="sf-skip" href="#sf-content">Skip to content</a>
      <div className="sf-announce">
        <span>Free delivery on every order</span>
        <span className="sf-announce-dot" aria-hidden="true" />
        <span>30-day returns</span>
        <span className="sf-announce-dot" aria-hidden="true" />
        <span>Checkout protected by SecureCloud</span>
      </div>
      <header className="sf-header">
        <div className="sf-header-inner">
          <button className="sf-icon-button sf-menu" onClick={() => setMenuOpen((value) => !value)}
            aria-expanded={menuOpen} aria-label={menuOpen ? "Close menu" : "Open menu"}>
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <Link className="sf-brand" route={{ name: "home" }} navigate={navigate} ariaLabel={`${SHOP.name} home`}>
            <span className="sf-brand-mark" aria-hidden="true">{SHOP.initial}</span>
            <span>{SHOP.name}</span>
          </Link>
          <nav className={`sf-nav ${menuOpen ? "open" : ""}`} aria-label="Store navigation">
            <Link route={{ name: "home" }} navigate={navigate} className={route.name === "home" && !activeCategory ? "active" : ""}>Shop all</Link>
            {CATEGORIES.map((category) => (
              <Link key={category} route={{ name: "home", category }} navigate={navigate}
                className={activeCategory === category ? "active" : ""}>{category}</Link>
            ))}
            {user && <Link route={{ name: "orders" }} navigate={navigate} className={route.name === "orders" || route.name === "order" ? "active" : ""}>My orders</Link>}
          </nav>
          <label className="sf-search">
            <Search size={16} aria-hidden="true" />
            <input type="search" placeholder="Search products" aria-label="Search products"
              value={query} onChange={(event) => search(event.target.value)} />
          </label>
          <div className="sf-account">
            {user
              ? <ProfileDropdown compact showPreferences={false}
                  accounts={[{ id: user.id, name: user.display_name, email: user.email, plan: user.role === "owner" ? "Owner" : "Customer" }]}
                  items={[
                    { label: "My orders", href: `${SHOP_BASE}/account/orders`, icon: <ShoppingBag className="size-4" /> },
                    ...(user.role === "owner" ? [{ label: "Store admin", href: `${SHOP.base}/admin`, icon: <ShieldCheck className="size-4" /> }] : []),
                  ]}
                  onSignOut={() => void logout()} />
              : <Link className="sf-signin" route={{ name: "login" }} navigate={navigate}>Sign in</Link>}
            <Link className="sf-cart-link" route={{ name: "cart" }} navigate={navigate} ariaLabel={`Cart ${count}`}>
              <ShoppingBag size={18} aria-hidden="true" />
              <span className="sf-cart-label">Cart</span>
              <b>{count}</b>
            </Link>
          </div>
        </div>
      </header>

      <main id="sf-content" tabIndex={-1}>
        {loading && <section className="sf-message"><Loader size="sm" title="Opening the store" subtitle="Loading products and your account" /></section>}
        {!loading && error && <StoreMessage title="The store is unavailable">{error}</StoreMessage>}
        {!loading && !error && (
          <>
            {route.name === "home" && <HomePage navigate={navigate} category={route.category} query={query} clearQuery={() => setQuery("")} />}
            {route.name === "product" && <ProductPage id={route.id} navigate={navigate} />}
            {route.name === "cart" && <CartPage navigate={navigate} />}
            {route.name === "checkout" && <CheckoutPage navigate={navigate} />}
            {route.name === "orders" && <OrdersPage navigate={navigate} />}
            {route.name === "order" && <OrderPage id={route.id} navigate={navigate} />}
            {route.name === "login" && <AuthLogin navigate={navigate} />}
            {route.name === "register" && <AuthRegister navigate={navigate} />}
          </>
        )}
      </main>

      <footer className="sf-footer">
        <div className="sf-footer-inner">
          <div className="sf-footer-brand">
            <Link className="sf-brand" route={{ name: "home" }} navigate={navigate}>
              <span className="sf-brand-mark" aria-hidden="true">{SHOP.initial}</span><span>{SHOP.name}</span>
            </Link>
            <p>Well-made everyday goods, delivered across India.</p>
          </div>
          <div>
            <h2>Shop</h2>
            {CATEGORIES.map((category) => <Link key={category} route={{ name: "home", category }} navigate={navigate}>{category}</Link>)}
          </div>
          <div>
            <h2>Account</h2>
            <Link route={{ name: "orders" }} navigate={navigate}>Order history</Link>
            <Link route={{ name: "cart" }} navigate={navigate}>Cart</Link>
            <a href={`${SHOP.base}/admin`}>Store admin</a>
          </div>
          <div>
            <h2>Security</h2>
            <p className="sf-footer-secure"><ShieldCheck size={16} aria-hidden="true" /> Services isolated and monitored by SecureCloud zero-trust middleware.</p>
          </div>
        </div>
        <div className="sf-footer-base">
          <span>© {new Date().getFullYear()} {SHOP.legal} · runs on the SecureCloud Mall platform</span>
          <span>Payments use a project simulator. No real charges are made.</span>
        </div>
      </footer>
    </div>
  );
}
