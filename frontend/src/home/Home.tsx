import { useEffect, useState } from "react";
import {
  ArrowDown, ArrowLeftRight, ArrowRight, Plus, Brain, Bug, Crosshair, Eye, FlaskConical, Lock, Mail, Network, Puzzle,
  Radar, Receipt, ShieldCheck, ShoppingBag, Store, Upload, Wallet,
} from "lucide-react";
import { listShops, THEMES, type MallShop } from "../shop";
import "./home.css";

/*
 * Root page, told as a story: two shops share one cloud, a plugin gets hacked, these are the
 * attacks it tries, this is how SecureCloud responds, now try it. Attack cards mirror the real
 * live-lab scenarios in backend/lab/scenarios.py, including the one the rules cannot stop.
 */

function useLabOnline() {
  const [online, setOnline] = useState<boolean | null>(null);
  useEffect(() => {
    let active = true;
    const load = () => fetch("/api/health")
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("offline"))))
      .then((value: { infrastructure?: { connected?: boolean } }) => { if (active) setOnline(Boolean(value.infrastructure?.connected)); })
      .catch(() => { if (active) setOnline(false); });
    void load();
    const timer = window.setInterval(() => void load(), 10_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  return online;
}

type Defence = "rules" | "ai";
const ATTACKS: Array<{ icon: typeof Bug; title: string; text: string; defence: Defence }> = [
  { icon: Bug, title: "Break into the other shop", text: "Tries Bloom's shop and data.", defence: "rules" },
  { icon: Network, title: "Try every door", text: "Pokes every service in the cloud.", defence: "rules" },
  { icon: Radar, title: "Scan for open ports", text: "Looks for a hidden way in.", defence: "rules" },
  { icon: Upload, title: "Steal data out", text: "Sends data to an outside server.", defence: "rules" },
  { icon: ArrowLeftRight, title: "Attack from the other side", text: "Bloom gets hacked and attacks Northstar.", defence: "rules" },
  { icon: Crosshair, title: "Abuse its own access", text: "Floods the one thing it is allowed to use.", defence: "ai" },
];

const RESPONSE = [
  { icon: Lock, title: "Block", text: "Anything not allowed is stopped." },
  { icon: Eye, title: "Watch", text: "Every connection is recorded." },
  { icon: Brain, title: "Spot", text: "AI notices strange behaviour." },
  { icon: ShieldCheck, title: "Lock up", text: "One click cuts the hacker off." },
];

/* One walled space per live shop, from the API. Northstar is the testbed shop with the plugin. */
function Tenant({ shop }: { shop: MallShop }) {
  const theme = THEMES.find((item) => item.id === shop.theme) ?? THEMES[0];
  return (
    <div className="st-tenant" style={{ ["--shop" as string]: theme.accent }}>
      <div className="st-tenant-head"><strong>{shop.name}</strong><span>{shop.tagline}</span></div>
      {shop.state === "live"
        ? <>
            <a href={`/${shop.slug}/shop`}><ShoppingBag size={18} aria-hidden="true" />Shop<ArrowRight size={16} aria-hidden="true" /></a>
            <a href={`/${shop.slug}/admin`}><Store size={18} aria-hidden="true" />Owner admin<ArrowRight size={16} aria-hidden="true" /></a>
          </>
        : <p className="st-tenant-wait">{shop.state === "provisioning" ? "Opening in a minute…" : "Unavailable"}</p>}
      <div className="st-internals">
        {shop.fixed && <span>Testbed</span>}
        {shop.slug === "northstar" && <span className="plugin"><Puzzle size={14} aria-hidden="true" />Has a shipping plugin</span>}
      </div>
    </div>
  );
}

function useMall() {
  const [shops, setShops] = useState<MallShop[] | null>(null);
  const [quota, setQuota] = useState<{ used: number; limit: number } | null>(null);
  useEffect(() => {
    listShops().then((value) => { setShops(value.items); setQuota(value.quota); }).catch(() => setShops([]));
  }, []);
  return { shops, quota };
}

/** A small card holding a real screenshot of the running app, in a browser-window frame. */
function Shot({ src, url, alt, href, caption, className = "" }: {
  src: string; url: string; alt: string; href?: string; caption?: string; className?: string;
}) {
  const frame = (
    <figure className={`st-shot ${className}`}>
      <div className="st-shot-bar" aria-hidden="true"><i /><i /><i /><span>{url}</span></div>
      <img src={src} alt={alt} width={1440} height={900} loading="lazy" decoding="async" />
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
  return href ? <a className="st-shot-link" href={href} aria-label={alt}>{frame}</a> : frame;
}

function Chapter({ index, title, children, id, aside }: { index: number; title: string; children: React.ReactNode; id?: string; aside?: React.ReactNode }) {
  return (
    <section className="st-chapter" id={id}>
      <div className="st-marker" aria-hidden="true"><span>{index}</span></div>
      <div className="st-body">
        <h2>{title}</h2>
        {aside
          ? <div className="st-split"><div className="st-split-main">{children}</div><aside className="st-aside">{aside}</aside></div>
          : children}
      </div>
    </section>
  );
}

export default function Home() {
  const online = useLabOnline();
  const { shops, quota } = useMall();
  const full = quota ? quota.used >= quota.limit : false;
  useEffect(() => { document.title = "SecureCloud · Zero trust for shared clouds"; }, []);

  return (
    <div className="st">
      <header className="st-nav">
        <a className="st-brand" href="/"><span>S</span>SecureCloud</a>
        <span className={`st-live ${online ? "on" : online === false ? "off" : ""}`}>
          <i aria-hidden="true" />{online === null ? "Checking lab" : online ? "Lab online" : "Lab offline"}
        </span>
        <a className="st-btn st-btn-sm st-btn-light" href="/start">Open a shop</a>
        <a className="st-btn st-btn-sm" href="/admin">Provider console</a>
      </header>

      <section className="st-hero">
        <div className="st-hero-copy">
          <h1>Many shops. One cloud.<br /><span>One gets hacked.</span></h1>
          <p className="st-lead">SecureCloud stops the hacker from spreading.</p>
          <div className="st-actions">
            <a className="st-btn" href="/start"><Plus size={18} aria-hidden="true" />Open your shop</a>
            <a className="st-btn st-btn-ghost" href="#story">See how it works<ArrowDown size={18} aria-hidden="true" /></a>
            <a className="st-btn st-btn-ghost" href="/lab"><FlaskConical size={18} aria-hidden="true" />Try an attack</a>
          </div>
        </div>
        <div className="st-hero-art" aria-hidden="true">
          <Shot className="back" src="/home/northstar-shop.jpg" url="northstar / shop" alt="" />
          <Shot className="front" src="/home/overview.jpg" url="securecloud / overview" alt="" />
          <span className="st-hero-badge"><ShieldCheck size={16} />Real screenshots</span>
        </div>
      </section>

      <main className="st-story" id="story">
        <Chapter index={1} title="Every shop gets its own walled space." aside={<>
          <Shot src="/home/northstar-shop.jpg" url="northstar / shop" alt="Open Northstar's storefront" href="/northstar/shop" caption="A real shop on the cluster" />
          <Shot src="/home/bloom-shop.jpg" url="bloom / shop" alt="Open Bloom's storefront" href="/bloom/shop" caption="Same template, different look" />
        </>}>
          <p className="st-text">Shops are made from one template. They share the cloud, but can't touch each other.</p>
          <div className="st-map">
            <div className="st-tenants">
              {(shops ?? []).map((shop) => <Tenant key={shop.slug} shop={shop} />)}
              <a className={`st-tenant st-tenant-new ${full ? "full" : ""}`} href="/start">
                <b><Plus size={22} aria-hidden="true" /></b>
                <strong>Open your shop</strong>
                <span>{quota ? `${quota.used} of ${quota.limit} spaces used` : "About a minute"}</span>
              </a>
            </div>
            <div className="st-platform">
              <strong>Shared by every shop</strong>
              <span><Receipt size={15} aria-hidden="true" />Order IDs</span><span><Wallet size={15} aria-hidden="true" />Payments</span><span><Mail size={15} aria-hidden="true" />Email</span>
            </div>
          </div>
        </Chapter>

        <Chapter index={2} title="Then one piece gets hacked.">
          <p className="st-text">In the testbed, Northstar's shipping plugin is taken over.</p>
          <div className="st-breach">
            <span className="st-breach-icon"><Puzzle size={30} aria-hidden="true" /></span>
            <div><strong>ShipFast plugin</strong><span>Now controlled by the hacker</span></div>
            <ArrowRight size={26} aria-hidden="true" />
            <strong className="st-breach-goal">Wants to reach everything</strong>
          </div>
        </Chapter>

        <Chapter index={3} title="What the hacker tries." aside={
          <Shot src="/home/lab.jpg" url="securecloud / live lab" href="/lab" alt="Open the live lab"
            caption="Live: 14 blocked, 0 got through" />
        }>
          <p className="st-text">All six are real attacks you can run.</p>
          <ul className="st-attacks">
            {ATTACKS.map(({ icon: Icon, title, text, defence }) => (
              <li key={title} className={defence}>
                <span className="st-attack-icon"><Icon size={22} aria-hidden="true" /></span>
                <h3>{title}</h3>
                <p>{text}</p>
                <em>{defence === "rules" ? "✓ Blocked" : "⚠ AI has to spot it"}</em>
              </li>
            ))}
          </ul>
        </Chapter>

        <Chapter index={4} title="What SecureCloud does." aside={
          <Shot src="/home/incident.jpg" url="securecloud / incident" href="/admin" alt="Open the provider console"
            caption="The incident, with the one-click lock" />
        }>
          <ol className="st-response">
            {RESPONSE.map(({ icon: Icon, title, text }) => (
              <li key={title}><span><Icon size={24} aria-hidden="true" /></span><h3>{title}</h3><p>{text}</p></li>
            ))}
          </ol>
        </Chapter>

        <Chapter index={5} title="Try it yourself." id="try">
          <div className="st-try">
            <a href="/northstar/shop"><img src="/home/northstar-shop.jpg" alt="" loading="lazy" /><b>1</b><ShoppingBag size={26} aria-hidden="true" /><strong>Buy something</strong><span>Normal shopping. All good.</span></a>
            <a href="/lab"><img src="/home/lab.jpg" alt="" loading="lazy" /><b>2</b><FlaskConical size={26} aria-hidden="true" /><strong>Launch an attack</strong><span>Watch it get blocked.</span></a>
            <a href="/admin"><img src="/home/incident.jpg" alt="" loading="lazy" /><b>3</b><ShieldCheck size={26} aria-hidden="true" /><strong>Lock the hacker out</strong><span>One click in the console.</span></a>
          </div>
        </Chapter>
      </main>

      <section className="st-close">
        <div>
          <h2>Your shop, walled off by default.</h2>
          <p>Name it, pick a look, launch. It gets its own space on the cloud in about a minute.</p>
        </div>
        <a className={`st-btn ${full ? "st-btn-disabled" : ""}`} href="/start"><Plus size={18} aria-hidden="true" />{full ? "The lab is full" : "Open your shop"}</a>
      </section>

      <footer className="st-foot">
        <span>SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation</span>
        <span>Isolated lab · test attacks only</span>
      </footer>
    </div>
  );
}
