import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { AddToCartButton } from "@/components/kokonutui/cart-button";
import ParticleButton from "@/components/kokonutui/particle-button";
import {
  ArrowLeft, ArrowRight, Check, CreditCard, Lock, Minus, Package, Plus, RotateCcw, ShieldCheck, Trash2, Truck,
} from "lucide-react";
import { useRetail } from "./RetailContext";
import type { Order, Product } from "./retailService";
import {
  categoryOf, dateOnly, dateTime, Link, money, ORDER_STEPS, OrderStatus, ProductImage, stockNote, type Navigate,
} from "./shared";
import { SHOP } from "../shop";

let justPlacedOrderId = "";

export function StoreMessage({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <section className="sf-message"><h1>{title}</h1><p>{children}</p>{action}</section>;
}

function AuthRequired({ navigate }: { navigate: Navigate }) {
  return (
    <StoreMessage title="Sign in to continue"
      action={<button className="sf-button sf-button-primary" onClick={() => navigate({ name: "login" })}>Sign in</button>}>
      Your cart and orders are linked to your SecureCloud Mall account.
    </StoreMessage>
  );
}

/* ------------------------------------------------------------------ Home */

type Sort = "featured" | "price-asc" | "price-desc" | "name";

export function HomePage({ navigate, category, query, clearQuery }: {
  navigate: Navigate; category?: string; query: string; clearQuery: () => void;
}) {
  const { products } = useRetail();
  const [sort, setSort] = useState<Sort>("featured");
  const featured = products.find((product) => product.id === "prod-backpack") ?? products[0];
  const categories = useMemo(() => Array.from(new Set(products.map(categoryOf))).sort(), [products]);
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const list = products.filter((product) =>
      (!category || categoryOf(product) === category) &&
      (!needle || `${product.name} ${product.description} ${categoryOf(product)}`.toLowerCase().includes(needle)));
    if (sort === "price-asc") list.sort((a, b) => a.price_minor - b.price_minor);
    if (sort === "price-desc") list.sort((a, b) => b.price_minor - a.price_minor);
    if (sort === "name") list.sort((a, b) => a.name.localeCompare(b.name));
    return list;
  }, [products, category, query, sort]);
  const filtered = Boolean(category || query.trim());

  return (
    <>
      {!filtered && featured && (
        <section className="sf-hero">
          <div className="sf-hero-copy">
            <p className="sf-eyebrow">{SHOP.eyebrow}</p>
            <h1>{SHOP.heroTitle}</h1>
            <p>{SHOP.heroText}</p>
            <div className="sf-hero-actions">
              <a href="#catalogue" className="sf-button sf-button-primary">Shop the collection <ArrowRight size={16} /></a>
              <Link className="sf-button sf-button-ghost" route={{ name: "product", id: featured.id }} navigate={navigate}>View {featured.name}</Link>
            </div>
            <dl className="sf-hero-stats">
              <div><dt>Delivery</dt><dd>2–4 days</dd></div>
              <div><dt>Returns</dt><dd>30 days</dd></div>
              <div><dt>Products</dt><dd>{products.length}</dd></div>
            </dl>
          </div>
          <Link className="sf-hero-media" route={{ name: "product", id: featured.id }} navigate={navigate} ariaLabel={`View ${featured.name}`}>
            <ProductImage src={featured.image_path} name={featured.name} />
            <span className="sf-hero-tag"><small>Featured</small><strong>{featured.name}</strong><em>{money(featured.price_minor)}</em></span>
          </Link>
        </section>
      )}

      {!filtered && (
        <section className="sf-values" aria-label={`Why shop with ${SHOP.name}`}>
          <div><Truck size={20} aria-hidden="true" /><span><strong>Free delivery</strong><small>On every order, no minimum</small></span></div>
          <div><RotateCcw size={20} aria-hidden="true" /><span><strong>30-day returns</strong><small>Unused items, no questions</small></span></div>
          <div><ShieldCheck size={20} aria-hidden="true" /><span><strong>Protected checkout</strong><small>Zero-trust isolated payment service</small></span></div>
        </section>
      )}

      <section className="sf-catalogue" id="catalogue">
        <div className="sf-section-head">
          <div>
            <p className="sf-eyebrow">{category ? "Category" : query.trim() ? "Search" : "Catalogue"}</p>
            <h2>{category ?? (query.trim() ? `Results for “${query.trim()}”` : "Shop all products")}</h2>
          </div>
          <div className="sf-toolbar">
            <div className="sf-chips" role="group" aria-label="Filter by category">
              <button className={!category ? "active" : ""} onClick={() => navigate({ name: "home" })}>All</button>
              {categories.map((item) => (
                <button key={item} className={category === item ? "active" : ""} onClick={() => navigate({ name: "home", category: item })}>{item}</button>
              ))}
            </div>
            <label className="sf-sort">
              <span>Sort</span>
              <select value={sort} onChange={(event) => setSort(event.target.value as Sort)} aria-label="Sort products">
                <option value="featured">Featured</option>
                <option value="price-asc">Price: low to high</option>
                <option value="price-desc">Price: high to low</option>
                <option value="name">Name</option>
              </select>
            </label>
          </div>
        </div>
        {visible.length
          ? <div className="sf-grid">{visible.map((product) => <ProductCard key={product.id} product={product} navigate={navigate} />)}</div>
          : <StoreMessage title="No products match"
              action={<button className="sf-button sf-button-ghost" onClick={() => { clearQuery(); navigate({ name: "home" }); }}>Clear filters</button>}>
              Try another search term or category.
            </StoreMessage>}
        <p className="sf-count">{visible.length} of {products.length} products</p>
      </section>
    </>
  );
}

function ProductCard({ product, navigate }: { product: Product; navigate: Navigate }) {
  const { user, service, refreshCart, cart } = useRetail();
  const inCart = cart?.items.find((item) => item.product_id === product.id)?.quantity ?? 0;
  const [quantity, setQuantity] = useState(inCart);
  const [error, setError] = useState("");
  const timer = useRef<number | undefined>(undefined);
  const stock = stockNote(product.stock_quantity);
  useEffect(() => { if (timer.current === undefined) setQuantity(inCart); }, [inCart]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  function change(next: number) {
    if (!user) { navigate({ name: "login" }); return; }
    setQuantity(next); setError("");
    window.clearTimeout(timer.current);
    // Taps and holds on the stepper settle into one cart update.
    timer.current = window.setTimeout(async () => {
      try {
        if (next === 0) await service.removeCartItem(product.id);
        else await service.setCartItem(product.id, next);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Could not update your cart");
      } finally {
        timer.current = undefined;
        await refreshCart().catch(() => undefined);
      }
    }, 350);
  }
  return (
    <article className="sf-card">
      <Link route={{ name: "product", id: product.id }} navigate={navigate} className="sf-card-media" ariaLabel={product.name}>
        <ProductImage src={product.image_path} name={product.name} />
        {stock.tone !== "in" && <span className={`sf-badge sf-badge-${stock.tone}`}>{stock.text}</span>}
      </Link>
      <div className="sf-card-body">
        <p className="sf-card-category">{categoryOf(product)}</p>
        <Link route={{ name: "product", id: product.id }} navigate={navigate} className="sf-card-title">{product.name}</Link>
        <p className="sf-card-desc">{product.description}</p>
        <div className="sf-card-foot">
          <strong className="sf-price">{money(product.price_minor)}</strong>
          {product.stock_quantity
            ? <AddToCartButton className="sf-stepper" name={product.name} label="Add" quantity={quantity}
                max={Math.min(20, product.stock_quantity)} onQuantityChange={change} />
            : <span className="sf-soldout">Out of stock</span>}
        </div>
        {error && <p className="sf-card-error" role="alert">{error}</p>}
      </div>
    </article>
  );
}

/* --------------------------------------------------------------- Product */

export function ProductPage({ id, navigate }: { id: string; navigate: Navigate }) {
  const { products, user, service, refreshCart, cart } = useRetail();
  const product = products.find((item) => item.id === id);
  const [quantity, setQuantity] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!product) {
    return <StoreMessage title="Product not found"
      action={<button className="sf-button sf-button-ghost" onClick={() => navigate({ name: "home" })}>Back to shop</button>}>
      This product is no longer available.</StoreMessage>;
  }
  const stock = stockNote(product.stock_quantity);
  const related = products.filter((item) => item.id !== product.id).slice(0, 3);
  const inCart = cart?.items.find((item) => item.product_id === product.id)?.quantity ?? 0;
  const max = Math.max(1, Math.min(20, product.stock_quantity - inCart));

  async function add(goToCheckout: boolean) {
    if (!user) return navigate({ name: "login" });
    setBusy(true); setError("");
    try {
      await service.setCartItem(product!.id, Math.min(inCart + quantity, 20));
      await refreshCart();
      navigate({ name: goToCheckout ? "checkout" : "cart" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not add to cart");
    } finally { setBusy(false); }
  }

  return (
    <>
      <section className="sf-product">
        <nav className="sf-crumbs" aria-label="Breadcrumb">
          <Link route={{ name: "home" }} navigate={navigate}>Shop</Link><span>/</span>
          <Link route={{ name: "home", category: categoryOf(product) }} navigate={navigate}>{categoryOf(product)}</Link><span>/</span>
          <span aria-current="page">{product.name}</span>
        </nav>
        <div className="sf-product-media"><ProductImage src={product.image_path} name={product.name} /></div>
        <div className="sf-product-info">
          <p className="sf-eyebrow">{categoryOf(product)} · {product.sku}</p>
          <h1>{product.name}</h1>
          <p className="sf-product-price">{money(product.price_minor)} <small>Inclusive of all taxes</small></p>
          <p className="sf-product-desc">{product.description}</p>
          <p className={`sf-stock sf-stock-${stock.tone}`}><span aria-hidden="true" />{stock.text}{stock.tone === "in" ? ` · ${product.stock_quantity} available` : ""}</p>
          <div className="sf-buy">
            <div className="sf-qty" role="group" aria-label="Quantity">
              <button aria-label="Decrease quantity" disabled={quantity <= 1} onClick={() => setQuantity((value) => value - 1)}><Minus size={16} /></button>
              <span aria-live="polite">{quantity}</span>
              <button aria-label="Increase quantity" disabled={quantity >= max} onClick={() => setQuantity((value) => value + 1)}><Plus size={16} /></button>
            </div>
            <button className="sf-button sf-button-primary sf-grow" disabled={busy || !product.stock_quantity} onClick={() => void add(false)}>
              {busy ? "Adding…" : "Add to cart"}
            </button>
          </div>
          <button className="sf-button sf-button-ghost sf-wide" disabled={busy || !product.stock_quantity} onClick={() => void add(true)}>Buy now</button>
          {error && <p className="sf-error" role="alert">{error}</p>}
          <ul className="sf-perks">
            <li><Truck size={18} aria-hidden="true" /><span><strong>Free delivery in 2–4 days</strong><small>Dispatched from our Bengaluru warehouse</small></span></li>
            <li><RotateCcw size={18} aria-hidden="true" /><span><strong>30-day returns</strong><small>Return unused items for a full refund</small></span></li>
            <li><Lock size={18} aria-hidden="true" /><span><strong>Protected checkout</strong><small>Orders run in an isolated SecureCloud tenant</small></span></li>
          </ul>
        </div>
      </section>
      {related.length > 0 && (
        <section className="sf-related">
          <div className="sf-section-head"><div><p className="sf-eyebrow">More to explore</p><h2>You may also like</h2></div></div>
          <div className="sf-grid sf-grid-3">{related.map((item) => <ProductCard key={item.id} product={item} navigate={navigate} />)}</div>
        </section>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ Cart */

export function CartPage({ navigate }: { navigate: Navigate }) {
  const { user, cart, service, refreshCart } = useRetail();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  if (!user) return <AuthRequired navigate={navigate} />;
  if (!cart?.items.length) {
    return <StoreMessage title="Your cart is empty"
      action={<button className="sf-button sf-button-primary" onClick={() => navigate({ name: "home" })}>Browse products</button>}>
      Products you add will appear here.</StoreMessage>;
  }
  async function update(id: string, quantity: number) {
    setBusy(id); setError("");
    try {
      if (quantity < 1) await service.removeCartItem(id); else await service.updateCartItem(id, quantity);
      await refreshCart();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update your cart");
    } finally { setBusy(""); }
  }
  const units = cart.items.reduce((sum, item) => sum + item.quantity, 0);
  return (
    <section className="sf-page sf-two-col">
      <div>
        <button className="sf-back" onClick={() => navigate({ name: "home" })}><ArrowLeft size={16} /> Continue shopping</button>
        <h1 className="sf-page-title">Your cart <small>{units} item{units === 1 ? "" : "s"}</small></h1>
        {error && <p className="sf-error" role="alert">{error}</p>}
        <ul className="sf-lines">
          {cart.items.map((item) => (
            <li key={item.product_id}>
              <Link route={{ name: "product", id: item.product_id }} navigate={navigate} className="sf-line-media" ariaLabel={item.name}>
                <ProductImage src={item.image_path} name={item.name} />
              </Link>
              <div className="sf-line-info">
                <Link route={{ name: "product", id: item.product_id }} navigate={navigate} className="sf-line-name">{item.name}</Link>
                <small>{item.sku} · {money(item.unit_price_minor)} each</small>
                <button className="sf-link-button" onClick={() => void update(item.product_id, 0)} disabled={busy === item.product_id}>
                  <Trash2 size={14} aria-hidden="true" /> Remove
                </button>
              </div>
              <div className="sf-qty sf-qty-small" role="group" aria-label={`Quantity for ${item.name}`}>
                <button aria-label="Decrease quantity" disabled={busy === item.product_id} onClick={() => void update(item.product_id, item.quantity - 1)}><Minus size={14} /></button>
                <span>{item.quantity}</span>
                <button aria-label="Increase quantity" disabled={busy === item.product_id || item.quantity >= Math.min(20, item.stock_quantity)} onClick={() => void update(item.product_id, item.quantity + 1)}><Plus size={14} /></button>
              </div>
              <strong className="sf-line-total">{money(item.line_total_minor)}</strong>
            </li>
          ))}
        </ul>
      </div>
      <aside className="sf-summary">
        <h2>Order summary</h2>
        <dl>
          <div><dt>Subtotal</dt><dd>{money(cart.subtotal_minor)}</dd></div>
          <div><dt>Delivery</dt><dd className="sf-free">Free</dd></div>
          <div className="sf-summary-total"><dt>Total</dt><dd>{money(cart.subtotal_minor)}</dd></div>
        </dl>
        <button className="sf-button sf-button-primary sf-wide" onClick={() => navigate({ name: "checkout" })}>Continue to checkout</button>
        <p className="sf-secure-note"><Lock size={14} aria-hidden="true" /> Payments are processed by the project simulator.</p>
      </aside>
    </section>
  );
}

/* -------------------------------------------------------------- Checkout */

function Steps({ current }: { current: 0 | 1 | 2 }) {
  const steps = ["Cart", "Delivery & payment", "Confirmation"];
  return (
    <ol className="sf-steps" aria-label="Checkout progress">
      {steps.map((step, index) => (
        <li key={step} className={index < current ? "done" : index === current ? "current" : ""} aria-current={index === current ? "step" : undefined}>
          <span>{index < current ? <Check size={12} /> : index + 1}</span>{step}
        </li>
      ))}
    </ol>
  );
}

export function CheckoutPage({ navigate }: { navigate: Navigate }) {
  const { user, cart, service, refreshCart, refreshOrders } = useRetail();
  const key = useRef(`checkout-${crypto.randomUUID()}`);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!user) return <AuthRequired navigate={navigate} />;
  if (!cart?.items.length) {
    return <StoreMessage title="Your cart is empty"
      action={<button className="sf-button sf-button-primary" onClick={() => navigate({ name: "home" })}>Browse products</button>}>
      Add a product before checking out.</StoreMessage>;
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const order = await service.checkout(values as Record<string, string>, key.current);
      await Promise.all([refreshCart(), refreshOrders()]);
      justPlacedOrderId = order.id;
      navigate({ name: "order", id: order.id });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Checkout failed. Check your details and try again.");
    } finally { setBusy(false); }
  }
  return (
    <section className="sf-page">
      <Steps current={1} />
      <div className="sf-two-col">
        <div>
          <button className="sf-back" onClick={() => navigate({ name: "cart" })}><ArrowLeft size={16} /> Back to cart</button>
          <h1 className="sf-page-title">Delivery and payment</h1>
          <form className="sf-form" onSubmit={(event) => void submit(event)}>
            <fieldset>
              <legend>Delivery address</legend>
              <label>Recipient<input name="recipient" required defaultValue={user.display_name} maxLength={100} autoComplete="name" /></label>
              <label>Phone<input name="phone" required defaultValue={user.phone} maxLength={24} autoComplete="tel" pattern="[+0-9() .\-]{7,24}" /></label>
              <label className="sf-span">Address line 1<input name="line1" required maxLength={160} autoComplete="address-line1" placeholder="House number and street" /></label>
              <label className="sf-span">Address line 2 <span className="sf-optional">Optional</span><input name="line2" maxLength={160} autoComplete="address-line2" placeholder="Apartment, landmark" /></label>
              <label>City<input name="city" required maxLength={80} autoComplete="address-level2" /></label>
              <label>State<input name="state" required maxLength={80} autoComplete="address-level1" /></label>
              <label>Postal code<input name="postal_code" required pattern="[A-Za-z0-9 \-]{3,12}" maxLength={12} autoComplete="postal-code" inputMode="numeric" /></label>
            </fieldset>
            <fieldset>
              <legend>Payment</legend>
              <div className="sf-pay-option">
                <CreditCard size={20} aria-hidden="true" />
                <span><strong>Project payment simulator</strong><small>No card details needed. A payment reference is generated when you place the order.</small></span>
                <Check size={18} aria-hidden="true" className="sf-pay-check" />
              </div>
            </fieldset>
            {error && <p className="sf-error" role="alert">{error}</p>}
            <ParticleButton type="submit" className="sf-pay-button" status={busy ? "pending" : error ? "error" : "idle"}
              pendingLabel="Placing order" errorLabel="Try again" icon={<Lock size={16} aria-hidden="true" />}>
              {`Pay ${money(cart.subtotal_minor)} and place order`}
            </ParticleButton>
          </form>
        </div>
        <aside className="sf-summary">
          <h2>Your items</h2>
          <ul className="sf-mini-lines">
            {cart.items.map((item) => (
              <li key={item.product_id}>
                <span className="sf-mini-media"><ProductImage src={item.image_path} name={item.name} /><b>{item.quantity}</b></span>
                <span>{item.name}<small>{item.sku}</small></span>
                <strong>{money(item.line_total_minor)}</strong>
              </li>
            ))}
          </ul>
          <dl>
            <div><dt>Subtotal</dt><dd>{money(cart.subtotal_minor)}</dd></div>
            <div><dt>Delivery</dt><dd className="sf-free">Free</dd></div>
            <div className="sf-summary-total"><dt>Total</dt><dd>{money(cart.subtotal_minor)}</dd></div>
          </dl>
        </aside>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- Orders */

export function OrdersPage({ navigate }: { navigate: Navigate }) {
  const { user, orders, products } = useRetail();
  if (!user) return <AuthRequired navigate={navigate} />;
  const images = new Map(products.map((product) => [product.id, product.image_path]));
  return (
    <section className="sf-page sf-narrow">
      <p className="sf-eyebrow">Your account</p>
      <h1 className="sf-page-title">Order history</h1>
      {!orders.length
        ? <StoreMessage title="No orders yet"
            action={<button className="sf-button sf-button-primary" onClick={() => navigate({ name: "home" })}>Start shopping</button>}>
            Orders you place will appear here.</StoreMessage>
        : <ul className="sf-order-list">
            {orders.map((order) => (
              <li key={order.id}>
                <Link route={{ name: "order", id: order.id }} navigate={navigate} className="sf-order-row">
                  <span className="sf-order-thumbs" aria-hidden="true">
                    {order.items.slice(0, 3).map((item) => <span key={item.id}><ProductImage src={images.get(item.product_id)} name={item.name_snapshot} /></span>)}
                  </span>
                  <span className="sf-order-main">
                    <strong>{order.order_number}</strong>
                    <small>{dateTime(order.created_at)} · {order.items.reduce((sum, item) => sum + item.quantity, 0)} items</small>
                  </span>
                  <OrderStatus status={order.status} />
                  <strong className="sf-order-total">{money(order.total_minor)}</strong>
                  <ArrowRight size={16} aria-hidden="true" className="sf-order-chevron" />
                </Link>
              </li>
            ))}
          </ul>}
    </section>
  );
}

export function OrderPage({ id, navigate }: { id: string; navigate: Navigate }) {
  const { user, orders, products } = useRetail();
  if (!user) return <AuthRequired navigate={navigate} />;
  const order = orders.find((item) => item.id === id);
  if (!order) return <StoreMessage title="Order not found">This order is not available in your account.</StoreMessage>;
  const fresh = justPlacedOrderId === order.id;
  const images = new Map(products.map((product) => [product.id, product.image_path]));
  return (
    <section className="sf-page">
      {fresh && <Steps current={2} />}
      <button className="sf-back" onClick={() => navigate({ name: "orders" })}><ArrowLeft size={16} /> All orders</button>
      {fresh && (
        <div className="sf-thanks" role="status">
          <span className="sf-thanks-icon"><Check size={20} /></span>
          <div><strong>Thank you, {order.customer.name.split(" ")[0]}. Your order is confirmed.</strong>
            <small>We have saved it to your account. You can track it here at any time.</small></div>
        </div>
      )}
      <div className="sf-receipt-head">
        <div>
          <p className="sf-eyebrow">Order</p>
          <h1>{order.order_number}</h1>
          <p>Placed {dateTime(order.created_at)}</p>
        </div>
        <OrderStatus status={order.status} />
      </div>
      <Tracking order={order} />
      <div className="sf-two-col sf-receipt">
        <section className="sf-panel">
          <h2>Items</h2>
          <ul className="sf-mini-lines">
            {order.items.map((item) => (
              <li key={item.id}>
                <span className="sf-mini-media"><ProductImage src={images.get(item.product_id)} name={item.name_snapshot} /><b>{item.quantity}</b></span>
                <span>{item.name_snapshot}<small>{item.sku_snapshot} · Qty {item.quantity}</small></span>
                <strong>{money(item.unit_price_minor * item.quantity)}</strong>
              </li>
            ))}
          </ul>
          <dl>
            <div><dt>Subtotal</dt><dd>{money(order.subtotal_minor)}</dd></div>
            <div><dt>Delivery</dt><dd className="sf-free">Free</dd></div>
            <div className="sf-summary-total"><dt>Total paid</dt><dd>{money(order.total_minor)}</dd></div>
          </dl>
        </section>
        <div className="sf-side-stack">
          <section className="sf-panel">
            <h2><Package size={16} aria-hidden="true" /> Delivery</h2>
            <address>
              {order.delivery_address.recipient}<br />
              {order.delivery_address.line1}<br />
              {order.delivery_address.line2 && <>{order.delivery_address.line2}<br /></>}
              {order.delivery_address.city}, {order.delivery_address.state} {order.delivery_address.postal_code}<br />
              {order.delivery_address.phone}
            </address>
          </section>
          <section className="sf-panel">
            <h2><CreditCard size={16} aria-hidden="true" /> Payment</h2>
            <p className="sf-pay-ref"><strong>{order.payment?.reference}</strong></p>
            <p className="sf-muted">Project payment simulator</p>
            <span className={`sf-status ${order.payment?.status === "paid" ? "sf-status-delivered" : "sf-status-cancelled"}`}>
              {order.payment?.status === "paid" ? "Paid" : order.payment?.status === "refunded" ? "Refunded" : "Failed"}
            </span>
          </section>
        </div>
      </div>
    </section>
  );
}

function Tracking({ order }: { order: Order }) {
  if (order.status === "cancelled") {
    return <div className="sf-tracking-cancelled">This order was cancelled on {dateOnly(order.updated_at)}. Any payment has been refunded.</div>;
  }
  const current = ORDER_STEPS.findIndex((step) => step.status === order.status);
  return (
    <ol className="sf-tracking" aria-label="Order progress">
      {ORDER_STEPS.map((step, index) => (
        <li key={step.status} className={index < current ? "done" : index === current ? "current" : ""}>
          <span className="sf-track-dot">{index <= current ? <Check size={12} /> : null}</span>
          <strong>{step.label}</strong>
          <small>{index === 0 ? dateOnly(order.created_at) : index === current ? dateOnly(order.updated_at) : step.detail}</small>
        </li>
      ))}
    </ol>
  );
}

/* ------------------------------------------------------------------ Auth */

function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  const { products } = useRetail();
  const image = products.find((product) => product.id === "prod-lamp")?.image_path ?? products[0]?.image_path;
  return (
    <section className="sf-auth">
      <div className="sf-auth-form">
        <p className="sf-eyebrow">SecureCloud Mall account · works on every shop</p>
        <h1>{title}</h1>
        <p className="sf-muted">{subtitle}</p>
        {children}
      </div>
      <aside className="sf-auth-art">
        {image && <img src={image} alt="" />}
        <div>
          <strong>One account for your cart, orders and deliveries.</strong>
          <small>Sessions and services are protected by SecureCloud zero-trust middleware.</small>
        </div>
      </aside>
    </section>
  );
}

export function AuthLogin({ navigate }: { navigate: Navigate }) {
  const { service, acceptUser } = useRetail();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const data = new FormData(event.currentTarget);
    try {
      const user = await service.login(String(data.get("email")), String(data.get("password")));
      await acceptUser(user);
      navigate({ name: "home" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign in failed");
    } finally { setBusy(false); }
  }
  return (
    <AuthShell title="Welcome back" subtitle="Sign in to see your cart and orders.">
      <form className="sf-form sf-form-stack" onSubmit={(event) => void submit(event)}>
        <label>Email<input name="email" type="email" required autoComplete="email" /></label>
        <label>Password<input name="password" type="password" required autoComplete="current-password" /></label>
        {error && <p className="sf-error" role="alert">{error}</p>}
        <button className="sf-button sf-button-primary sf-wide" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="sf-auth-switch">New here? <button className="sf-link-button" onClick={() => navigate({ name: "register" })}>Create an account</button></p>
    </AuthShell>
  );
}

export function AuthRegister({ navigate }: { navigate: Navigate }) {
  const { service } = useRetail();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const data = new FormData(event.currentTarget);
    const password = String(data.get("password"));
    if (password !== String(data.get("confirmation"))) { setError("Passwords do not match"); setBusy(false); return; }
    try {
      await service.register({ email: String(data.get("email")), password, display_name: String(data.get("display_name")), phone: String(data.get("phone")) });
      navigate({ name: "login" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create account");
    } finally { setBusy(false); }
  }
  return (
    <AuthShell title="Create your account" subtitle="Save your cart, check out faster and track every order.">
      <form className="sf-form sf-form-stack" onSubmit={(event) => void submit(event)}>
        <label>Full name<input name="display_name" required maxLength={100} autoComplete="name" /></label>
        <label>Email<input name="email" type="email" required autoComplete="email" /></label>
        <label>Phone <span className="sf-optional">Optional</span><input name="phone" type="tel" maxLength={24} autoComplete="tel" /></label>
        <label>Password<input name="password" type="password" minLength={14} maxLength={256} required autoComplete="new-password" /><small>Use at least 14 characters.</small></label>
        <label>Confirm password<input name="confirmation" type="password" minLength={14} required autoComplete="new-password" /></label>
        {error && <p className="sf-error" role="alert">{error}</p>}
        <button className="sf-button sf-button-primary sf-wide" disabled={busy}>{busy ? "Creating account…" : "Create account"}</button>
      </form>
      <p className="sf-auth-switch">Already registered? <button className="sf-link-button" onClick={() => navigate({ name: "login" })}>Sign in</button></p>
    </AuthShell>
  );
}
