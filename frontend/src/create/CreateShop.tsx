import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ArrowLeft, ArrowRight, Check, Loader2, Plus, Rocket, Store, X } from "lucide-react";
import { ACCOUNTS_API, THEMES, type ShopTheme } from "../shop";
import "./create.css";

/*
 * Self-service shop signup. A signed-in user names their shop, picks a look and categories,
 * and launches it. Launching asks SecureCloud for a new isolated tenant; the progress screen
 * shows the reconciler's real state, polled from the API, until every service is running.
 */

type Quota = { used: number; limit: number };
type Step = { name: string; template: "web" | "api" | "database"; observed: string };
type Status = { state: "live" | "provisioning" | "failed"; operation?: string; error?: string | null; steps: Step[] };
type Owned = { slug: string; name: string; theme: ShopTheme; status: Status };
type Me = { csrf: string; shops: Owned[]; quota: Quota };

const STEPS = ["Name", "Look", "Products", "Launch"] as const;
const SERVICE_NAMES: Record<Step["template"], string> = { web: "Storefront", api: "Order system", database: "Database" };
const slugify = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 24).replace(/-+$/, "");

async function readError(response: Response, fallback: string) {
  const body = await response.json().catch(() => null) as { detail?: string } | null;
  return new Error(body?.detail ?? fallback);
}

export default function CreateShop() {
  const [me, setMe] = useState<Me | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const load = useCallback(async () => {
    const response = await fetch("/api/mall/me");
    if (response.status === 401) { setSignedOut(true); setMe(null); return; }
    if (response.ok) { setSignedOut(false); setMe(await response.json()); }
  }, []);
  useEffect(() => { document.title = "Open your shop · SecureCloud"; void load(); }, [load]);

  return (
    <div className="cs">
      <header className="cs-top">
        <a className="cs-brand" href="/"><span>S</span>SecureCloud</a>
        <span className="cs-top-title">Open your shop</span>
      </header>
      <main className="cs-main">
        {signedOut ? <SignIn onDone={load} />
          : !me ? <p className="cs-wait"><Loader2 className="cs-spin" size={18} />Loading…</p>
          : me.shops.length ? <Progress shop={me.shops[0]} />
          : <Wizard me={me} onCreated={load} />}
      </main>
    </div>
  );
}

/* --------------------------------------------------------------------------- sign in */

function SignIn({ onDone }: { onDone: () => Promise<void> }) {
  const [mode, setMode] = useState<"in" | "new">("in");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email")), password = String(form.get("password"));
    const post = (path: string, body: object) => fetch(`${ACCOUNTS_API}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    try {
      if (mode === "new") {
        const created = await post("/auth/register", { email, password, display_name: String(form.get("name")) });
        if (!created.ok) throw await readError(created, "Could not create the account");
      }
      const login = await post("/auth/login", { email, password });
      if (!login.ok) throw await readError(login, "Sign in failed");
      await onDone();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Sign in failed"); }
    finally { setBusy(false); }
  }
  return (
    <section className="cs-card cs-auth">
      <h1>Open your own shop</h1>
      <p>Sign in first. Your shop gets its own isolated space on the cloud.</p>
      <div className="cs-tabs" role="tablist">
        <button role="tab" aria-selected={mode === "in"} className={mode === "in" ? "on" : ""} onClick={() => setMode("in")}>Sign in</button>
        <button role="tab" aria-selected={mode === "new"} className={mode === "new" ? "on" : ""} onClick={() => setMode("new")}>New account</button>
      </div>
      <form onSubmit={(event) => void submit(event)}>
        {mode === "new" && <label>Your name<input name="name" required minLength={2} maxLength={100} autoComplete="name" /></label>}
        <label>Email<input name="email" type="email" required autoComplete="email" /></label>
        <label>Password<input name="password" type="password" required minLength={mode === "new" ? 14 : 1} autoComplete={mode === "new" ? "new-password" : "current-password"} />
          {mode === "new" && <small>At least 14 characters.</small>}</label>
        {error && <p className="cs-error" role="alert">{error}</p>}
        <button className="cs-btn" disabled={busy}>{busy ? "One moment…" : mode === "new" ? "Create account" : "Sign in"}<ArrowRight size={17} /></button>
      </form>
    </section>
  );
}

/* --------------------------------------------------------------------------- wizard */

function Wizard({ me, onCreated }: { me: Me; onCreated: () => Promise<void> }) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [tagline, setTagline] = useState("");
  const [theme, setTheme] = useState<ShopTheme>("forest");
  const [heroTitle, setHeroTitle] = useState("");
  const [heroText, setHeroText] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const full = me.quota.used >= me.quota.limit;
  const address = slugTouched ? slug : slugify(name);

  const valid = [
    name.trim().length >= 2 && /^[a-z][a-z0-9-]{2,22}[a-z0-9]$/.test(address) && tagline.trim().length >= 2,
    heroTitle.trim().length >= 2 && heroText.trim().length >= 2,
    categories.length >= 1,
    !full,
  ];

  function addCategory() {
    const value = draft.trim().replace(/\s+/g, " ");
    if (value.length < 2 || value.length > 24 || categories.includes(value) || categories.length >= 6) return;
    setCategories([...categories, value]); setDraft("");
  }

  async function launch() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/mall/shops", {
        method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": me.csrf },
        body: JSON.stringify({ slug: address, name: name.trim(), tagline: tagline.trim(), hero_title: heroTitle.trim(), hero_text: heroText.trim(), theme, categories }),
      });
      if (!response.ok) throw await readError(response, "Could not create the shop");
      await onCreated();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not create the shop"); setBusy(false); }
  }

  return (
    <div className="cs-wizard">
      <section className="cs-card">
        <ol className="cs-steps">
          {STEPS.map((label, index) => (
            <li key={label} className={index === step ? "on" : index < step ? "done" : ""}>
              <b>{index < step ? <Check size={14} /> : index + 1}</b>{label}
            </li>
          ))}
        </ol>

        {step === 0 && (
          <div className="cs-fields">
            <h1>Name your shop</h1>
            <label>Shop name<input value={name} onChange={(event) => setName(event.target.value)} maxLength={40} placeholder="Terra Pots" autoFocus /></label>
            <label>Shop address
              <span className="cs-address"><em>/</em><input value={address} maxLength={24} onChange={(event) => { setSlugTouched(true); setSlug(slugify(event.target.value)); }} placeholder="terra-pots" /><em>/shop</em></span>
              <small>Lowercase letters, numbers and dashes.</small>
            </label>
            <label>One line about it<input value={tagline} onChange={(event) => setTagline(event.target.value)} maxLength={60} placeholder="Handmade clay planters" /></label>
          </div>
        )}

        {step === 1 && (
          <div className="cs-fields">
            <h1>Pick a look</h1>
            <div className="cs-themes" role="radiogroup" aria-label="Theme">
              {THEMES.map((item) => (
                <button key={item.id} role="radio" aria-checked={theme === item.id} className={theme === item.id ? "on" : ""} onClick={() => setTheme(item.id)}>
                  <i style={{ background: item.accent }} /><span>{item.name}</span>
                </button>
              ))}
            </div>
            <label>Big headline<input value={heroTitle} onChange={(event) => setHeroTitle(event.target.value)} maxLength={60} placeholder="Grow something lovely." /></label>
            <label>Short intro<textarea value={heroText} onChange={(event) => setHeroText(event.target.value)} maxLength={200} rows={3} placeholder="Planters thrown by hand in Pune." /></label>
          </div>
        )}

        {step === 2 && (
          <div className="cs-fields">
            <h1>What do you sell?</h1>
            <p className="cs-hint">Add up to 6 categories. You add products later in your shop admin.</p>
            <div className="cs-chips">
              {categories.map((item) => (
                <span key={item}>{item}<button aria-label={`Remove ${item}`} onClick={() => setCategories(categories.filter((c) => c !== item))}><X size={13} /></button></span>
              ))}
            </div>
            <div className="cs-add">
              <input value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={24} placeholder="Planters"
                onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addCategory(); } }} />
              <button className="cs-btn cs-btn-ghost" onClick={addCategory} disabled={categories.length >= 6}><Plus size={16} />Add</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="cs-fields">
            <h1>Ready to launch</h1>
            <dl className="cs-review">
              <div><dt>Shop</dt><dd>{name}</dd></div>
              <div><dt>Address</dt><dd>/{address}/shop</dd></div>
              <div><dt>Look</dt><dd>{THEMES.find((item) => item.id === theme)?.name}</dd></div>
              <div><dt>Categories</dt><dd>{categories.join(", ")}</dd></div>
            </dl>
            <p className={`cs-quota ${full ? "full" : ""}`}>{me.quota.used} of {me.quota.limit} lab shops in use{full ? ". The lab is full right now." : "."}</p>
            <p className="cs-hint">SecureCloud creates an isolated space just for your shop: its own namespace, network walls that block everyone else, and three services.</p>
          </div>
        )}

        {error && <p className="cs-error" role="alert">{error}</p>}
        <div className="cs-nav">
          {step > 0 && <button className="cs-btn cs-btn-ghost" onClick={() => setStep(step - 1)} disabled={busy}><ArrowLeft size={16} />Back</button>}
          {step < 3
            ? <button className="cs-btn" onClick={() => setStep(step + 1)} disabled={!valid[step]}>Next<ArrowRight size={16} /></button>
            : <button className="cs-btn" onClick={() => void launch()} disabled={busy || !valid[3]}><Rocket size={16} />{busy ? "Launching…" : "Launch my shop"}</button>}
        </div>
      </section>

      <Preview name={name || "Your shop"} tagline={tagline} theme={theme} heroTitle={heroTitle || "Your big headline"} heroText={heroText || "A short intro about what you sell."} categories={categories} />
    </div>
  );
}

function Preview({ name, tagline, theme, heroTitle, heroText, categories }: {
  name: string; tagline: string; theme: ShopTheme; heroTitle: string; heroText: string; categories: string[];
}) {
  const accent = useMemo(() => THEMES.find((item) => item.id === theme) ?? THEMES[0], [theme]);
  return (
    <aside className="cs-preview" aria-label="Storefront preview" style={{ ["--cs-accent" as string]: accent.accent, ["--cs-soft" as string]: accent.soft }}>
      <p className="cs-preview-label">Live preview</p>
      <div className="cs-window">
        <div className="cs-window-bar"><i /><i /><i /></div>
        <div className="cs-shop">
          <div className="cs-shop-band">Free delivery · Checkout protected by SecureCloud</div>
          <div className="cs-shop-head"><b>{name.trim()[0]?.toUpperCase() ?? "S"}</b><strong>{name}</strong><span>{(categories.length ? categories : ["Shop all"]).slice(0, 3).join(" · ")}</span></div>
          <div className="cs-shop-hero">
            <small>{tagline || "What makes it special"}</small>
            <h2>{heroTitle}</h2>
            <p>{heroText}</p>
            <span className="cs-shop-cta">Shop the collection →</span>
          </div>
        </div>
      </div>
    </aside>
  );
}

/* --------------------------------------------------------------------------- progress */

function Progress({ shop }: { shop: Owned }) {
  const [status, setStatus] = useState<Status>(shop.status);
  useEffect(() => {
    if (status.state === "live") return;
    const timer = window.setInterval(async () => {
      const response = await fetch(`/api/mall/shops/${encodeURIComponent(shop.slug)}/status`).catch(() => null);
      if (response?.ok) setStatus(await response.json());
    }, 2000);
    return () => window.clearInterval(timer);
  }, [shop.slug, status.state]);
  const live = status.state === "live";
  const failed = status.state === "failed";

  return (
    <section className="cs-card cs-progress">
      <span className={`cs-badge ${live ? "live" : failed ? "failed" : ""}`}>{live ? <Check size={28} /> : failed ? <X size={28} /> : <Loader2 className="cs-spin" size={28} />}</span>
      <h1>{live ? `${shop.name} is live.` : failed ? "Something went wrong." : `Building ${shop.name}…`}</h1>
      <p>{live ? "Your shop has its own isolated space on the cloud." : failed ? status.error ?? "Provisioning failed." : "Creating your isolated space. This takes about a minute."}</p>
      <ul className="cs-checklist">
        <li className="done"><Check size={16} />Request accepted</li>
        {status.steps.map((item) => (
          <li key={item.name} className={item.observed === "running" ? "done" : failed ? "failed" : "wait"}>
            {item.observed === "running" ? <Check size={16} /> : failed ? <X size={16} /> : <Loader2 className="cs-spin" size={16} />}
            {SERVICE_NAMES[item.template]}<code>{item.name}</code>
          </li>
        ))}
        <li className={live ? "done" : "wait"}>{live ? <Check size={16} /> : <span className="cs-dot" />}Shop open for customers</li>
      </ul>
      {live && (
        <div className="cs-nav">
          <a className="cs-btn" href={`/${shop.slug}/admin/products`}><Store size={16} />Add products</a>
          <a className="cs-btn cs-btn-ghost" href={`/${shop.slug}/shop`}>Open storefront<ArrowRight size={16} /></a>
        </div>
      )}
    </section>
  );
}
