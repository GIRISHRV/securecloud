import { useEffect, type ReactNode } from "react";
import { Search, X } from "lucide-react";

export const money = (minor: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(minor / 100);

export const moneyCompact = (minor: number) => {
  const rupees = minor / 100;
  if (rupees >= 100000) return `₹${(rupees / 100000).toFixed(rupees >= 1000000 ? 0 : 1)}L`;
  if (rupees >= 1000) return `₹${(rupees / 1000).toFixed(rupees >= 10000 ? 0 : 1)}k`;
  return `₹${Math.round(rupees)}`;
};

export const when = (seconds: number | null | undefined) =>
  seconds ? new Date(seconds * 1000).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "Never";

export function relative(seconds: number | null | undefined) {
  if (!seconds) return "Never";
  const delta = Date.now() / 1000 - seconds;
  if (delta < 60) return "Just now";
  if (delta < 3600) return `${Math.floor(delta / 60)} min ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)} h ago`;
  if (delta < 7 * 86400) return `${Math.floor(delta / 86400)} d ago`;
  return new Date(seconds * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "?";
}

export function PageHead({ title, description, children }: { title: string; description?: ReactNode; children?: ReactNode }) {
  return (
    <div className="ad-page-head">
      <div><h1>{title}</h1>{description && <p>{description}</p>}</div>
      {children && <div className="ad-page-actions">{children}</div>}
    </div>
  );
}

export function Panel({ title, subtitle, action, children, className = "", flush = false }: {
  title?: ReactNode; subtitle?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; flush?: boolean;
}) {
  return (
    <section className={`ad-panel ${className}`}>
      {(title || action) && (
        <header>
          <div>{title && <h2>{title}</h2>}{subtitle && <p>{subtitle}</p>}</div>
          {action}
        </header>
      )}
      <div className={flush ? "ad-panel-flush" : "ad-panel-body"}>{children}</div>
    </section>
  );
}

const GOOD = ["paid", "delivered", "active", "online", "published", "exact", "allowed", "restored", "succeeded"];
const BAD = ["cancelled", "unavailable", "offline", "alert", "denied", "failed", "refunded"];
const WARN = ["processing", "packing", "quarantined", "review", "inconclusive", "low"];
const INFO = ["placed", "shipped"];

export function Status({ value, label }: { value: string; label?: string }) {
  const safe = value.toLowerCase();
  const tone = GOOD.includes(safe) ? "good" : BAD.includes(safe) ? "bad" : WARN.includes(safe) ? "warn" : INFO.includes(safe) ? "info" : "neutral";
  return <span className={`ad-status ad-status-${tone}`}><i aria-hidden="true" />{label ?? value}</span>;
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return <div className="ad-empty"><strong>{title}</strong>{children && <p>{children}</p>}{action}</div>;
}

export function Avatar({ name }: { name: string }) {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) % 360;
  return <span className="ad-avatar" style={{ background: `hsl(${hash} 45% 92%)`, color: `hsl(${hash} 45% 30%)` }} aria-hidden="true">{initials(name)}</span>;
}

export function Drawer({ open, title, subtitle, onClose, children, footer }: {
  open: boolean; title: ReactNode; subtitle?: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="ad-drawer-layer">
      <button className="ad-drawer-scrim" aria-label="Close panel" onClick={onClose} />
      <aside className="ad-drawer" role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : "Details"}>
        <header>
          <div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
          <button className="ad-icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </header>
        <div className="ad-drawer-body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </aside>
    </div>
  );
}

export function FilterInput({ value, onChange, label }: { value: string; onChange: (value: string) => void; label: string }) {
  return (
    <label className="ad-filter">
      <Search size={15} aria-hidden="true" />
      <input type="search" aria-label={label} placeholder={label} value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

export function Tabs<T extends string>({ value, options, onChange, label }: {
  value: T; options: Array<{ id: T; label: string; count?: number }>; onChange: (value: T) => void; label: string;
}) {
  return (
    <div className="ad-tabs" role="tablist" aria-label={label}>
      {options.map((option) => (
        <button key={option.id} role="tab" aria-selected={value === option.id} className={value === option.id ? "active" : ""} onClick={() => onChange(option.id)}>
          {option.label}{option.count !== undefined && <span>{option.count}</span>}
        </button>
      ))}
    </div>
  );
}
