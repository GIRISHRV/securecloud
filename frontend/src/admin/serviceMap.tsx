/* Service map shared by the attack testbed and the provider overview.
   The testbed uses its fixed topology; the overview lays the map out from the live workload
   list, one zone per tenant, so any number of shops appears without code changes.
   Edges are drawn only for traffic Hubble actually observed. */

type Node = { x: number; y: number; label: string };
type Zone = { x: number; y: number; w: number; h: number; label: string; kind: "retail" | "vendor" | "platform" };
export type MapLayout = {
  width: number; height: number;
  nodes: Record<string, Node>;
  zones: Zone[];
  walls: number[];  // x positions of vertical tenant walls (shop zones only)
  base: Array<[string, string]>;
};

/* The testbed's fixed topology (Northstar, Bloom, ShipFast, shared platform). */
export const FIXED_LAYOUT: MapLayout = {
  width: 920, height: 530,
  nodes: {
    shopper: { x: 75, y: 110, label: "Shopper" },
    "northstar-web": { x: 215, y: 110, label: "Storefront" },
    "northstar-api": { x: 370, y: 110, label: "Order API" },
    "northstar-database": { x: 520, y: 110, label: "Orders DB" },
    "shipfast-plugin": { x: 215, y: 300, label: "ShipFast plugin" },
    "bloom-web": { x: 795, y: 80, label: "Storefront" },
    "bloom-api": { x: 795, y: 200, label: "Order API" },
    "bloom-database": { x: 795, y: 325, label: "Orders DB" },
    "order-ids": { x: 330, y: 465, label: "Order IDs" },
    payments: { x: 520, y: 465, label: "Payments" },
    email: { x: 710, y: 465, label: "Email" },
    internet: { x: 862, y: 465, label: "Internet" },
  },
  zones: [
    { x: 12, y: 12, w: 580, h: 376, label: "Northstar (bags)", kind: "retail" },
    { x: 680, y: 12, w: 228, h: 376, label: "Bloom (candles)", kind: "vendor" },
    { x: 12, y: 408, w: 896, h: 112, label: "Mall platform (shared)", kind: "platform" },
  ],
  walls: [636],
  base: [
    ["shopper", "northstar-web"], ["northstar-web", "northstar-api"], ["northstar-api", "northstar-database"],
    ["shipfast-plugin", "northstar-api"], ["bloom-web", "bloom-api"], ["bloom-api", "bloom-database"],
    ["northstar-api", "order-ids"], ["northstar-api", "payments"], ["northstar-api", "email"],
    ["bloom-api", "order-ids"], ["bloom-api", "payments"], ["bloom-api", "email"],
  ],
};

/** Minimal workload shape the auto-layout needs (matches the provider's platform services). */
export type LayoutService = { name: string; tenant: string; kind: "shop" | "platform" | "plugin"; calls: string[] };

const ROLE_LABEL: Record<string, string> = { web: "Storefront", api: "Order API", database: "Orders DB" };
const pretty = (name: string) => name.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

/** Lay out any number of tenants: shop zones side by side with walls between, platform below. */
export function buildLayout(services: LayoutService[]): MapLayout {
  const tenants = [...new Set(services.filter((s) => s.kind !== "platform").map((s) => s.tenant))];
  const platform = services.filter((s) => s.kind === "platform");
  const zoneW = 230, gap = 46, pad = 12, top = 12, zoneH = 400;
  const width = Math.max(920, pad * 2 + tenants.length * zoneW + Math.max(0, tenants.length - 1) * gap);
  const nodes: Record<string, Node> = {};
  const zones: Zone[] = [];
  const walls: number[] = [];
  const base: Array<[string, string]> = [];

  tenants.forEach((tenant, index) => {
    const x = pad + index * (zoneW + gap), cx = x + zoneW / 2;
    zones.push({ x, y: top, w: zoneW, h: zoneH, label: tenant, kind: index % 2 ? "vendor" : "retail" });
    if (index > 0) walls.push(x - gap / 2);
    const own = services.filter((s) => s.tenant === tenant && s.kind !== "platform");
    const role = (s: LayoutService) => (s.kind === "plugin" ? "plugin" : s.name.split("-").pop() ?? "");
    const order = ["web", "api", "database", "plugin"];
    own.sort((a, b) => order.indexOf(role(a)) - order.indexOf(role(b)))
      .forEach((service, row) => {
        const plugin = `${pretty(service.name.replace(/-plugin$/, "")).replace("Shipfast", "ShipFast")} plugin`;
        nodes[service.name] = { x: cx, y: top + 78 + row * 92, label: service.kind === "plugin" ? plugin : ROLE_LABEL[role(service)] ?? pretty(service.name) };
      });
    for (const service of own) for (const call of service.calls) base.push([service.name, call]);
  });

  const platformY = top + zoneH + 20;
  zones.push({ x: pad, y: platformY, w: width - pad * 2, h: 112, label: "Mall platform (shared)", kind: "platform" });
  const row = [...platform.map((s) => s.name), "internet"];
  row.forEach((name, index) => {
    const label = name === "internet" ? "Internet" : pretty(name).replace("Order Ids", "Order IDs");
    nodes[name] = { x: pad + ((index + 1) * (width - pad * 2)) / (row.length + 1), y: platformY + 60, label };
  });
  return { width, height: platformY + 112 + pad, nodes, zones, walls, base: base.filter(([a, b]) => nodes[a] && nodes[b]) };
}

/** `recent: false` draws the edge without moving packets, so old traffic does not look live. */
export type MapEdge = { from: string; to: string; allowed: number; blocked: number; recent?: boolean };

export function addEdge(map: Map<string, MapEdge>, from: string, to: string, allowed: number, blocked: number,
  recent?: boolean, layout: MapLayout = FIXED_LAYOUT) {
  if (!layout.nodes[from] || !layout.nodes[to] || allowed + blocked === 0) return;
  const key = `${from}>${to}`;
  const edge = map.get(key) ?? { from, to, allowed: 0, blocked: 0, recent: false };
  edge.allowed += allowed; edge.blocked += blocked;
  edge.recent = recent === undefined ? undefined : Boolean(edge.recent || recent);
  map.set(key, edge);
}

/** `showCounts: false` labels edges "allowed"/"blocked" without numbers, for callers whose
 *  edges are deduplicated paths rather than counted attempts. */
export function ServiceMap({ edges, quarantined, source, live, selected, onSelect, className = "", showCounts = true, layout = FIXED_LAYOUT }: {
  edges: MapEdge[]; quarantined: Set<string>; source?: string | null; live: boolean;
  selected?: string | null; onSelect?: (id: string) => void; className?: string; showCounts?: boolean; layout?: MapLayout;
}) {
  const { nodes } = layout;
  const touched = new Set(edges.flatMap((edge) => [edge.from, edge.to]));
  const line = (from: string, to: string) => ({ x1: nodes[from].x, y1: nodes[from].y, x2: nodes[to].x, y2: nodes[to].y });
  const shopBottom = Math.max(...layout.zones.filter((z) => z.kind !== "platform").map((z) => z.y + z.h), 0);
  return (
    <div className={`lab2-map ${className}`}>
      <svg viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label="Service map with live connection verdicts">
        {layout.zones.map((zone) => (
          <g key={zone.label + zone.x}>
            <rect className={`zone ${zone.kind}`} x={zone.x} y={zone.y} width={zone.w} height={zone.h} rx="16" />
            <text className="zone-label" x={zone.x + 18} y={zone.y + 26}>{zone.label}</text>
          </g>
        ))}
        {layout.walls.map((x) => (
          <g key={x}>
            <line className="wall" x1={x} x2={x} y1={30} y2={shopBottom / 2 - 18} />
            <line className="wall" x1={x} x2={x} y1={shopBottom / 2 + 22} y2={shopBottom - 18} />
            <text className="wall-label" x={x} y={shopBottom / 2 + 6} textAnchor="middle">wall</text>
          </g>
        ))}

        {layout.base.map(([from, to]) => <line key={`b-${from}-${to}`} className="edge-base" {...line(from, to)} />)}

        {edges.map((edge) => {
          const blocked = edge.blocked > 0 && edge.allowed === 0;
          const mixed = edge.blocked > 0 && edge.allowed > 0;
          const pts = line(edge.from, edge.to);
          // A blocked cross-tenant attempt stops at the first wall it crosses; other blocks stop halfway.
          const crossed = layout.walls
            .filter((x) => (pts.x1 - x) * (pts.x2 - x) < 0)
            .sort((a, b) => Math.abs(a - pts.x1) - Math.abs(b - pts.x1))[0];
          const t = blocked && crossed !== undefined ? (crossed - pts.x1) / (pts.x2 - pts.x1) : 0.5;
          const stop = { x: pts.x1 + (pts.x2 - pts.x1) * t, y: pts.y1 + (pts.y2 - pts.y1) * t };
          const end = blocked ? stop : { x: pts.x2, y: pts.y2 };
          const path = `M${pts.x1},${pts.y1} L${end.x},${end.y}`;
          const towardSource = pts.x1 > stop.x ? 1 : -1;
          return (
            <g key={`${edge.from}-${edge.to}`} className={`${blocked ? "edge blocked" : mixed ? "edge mixed" : "edge allowed"} ${edge.recent === false ? "stale" : ""}`}>
              <line x1={pts.x1} y1={pts.y1} x2={end.x} y2={end.y} className="edge-line" />
              {edge.recent !== false && [0, 0.3, 0.6].map((delay) => (
                <circle key={delay} r="5" className="packet">
                  <animateMotion dur="0.9s" begin={`${delay}s`} repeatCount="indefinite" path={path} />
                </circle>
              ))}
              {(blocked || mixed) && (
                <g transform={`translate(${stop.x} ${stop.y})`} className="stop">
                  <circle r="11" /><path d="M-5,-5 L5,5 M5,-5 L-5,5" />
                </g>
              )}
              <text className="edge-count" x={blocked ? stop.x + towardSource * 16 : stop.x} y={blocked ? stop.y + 4 : stop.y - 14}
                textAnchor={blocked ? (towardSource > 0 ? "start" : "end") : "middle"}>
                {!showCounts
                  ? (blocked ? "blocked" : mixed ? "blocked · ok" : "ok")
                  : blocked ? `${edge.blocked} blocked` : mixed ? `${edge.blocked} blocked · ${edge.allowed} ok` : `${edge.allowed} ok`}
              </text>
            </g>
          );
        })}

        {Object.entries(nodes).map(([id, node]) => {
          const isSource = id === source;
          const isQuarantined = quarantined.has(id);
          const clickable = onSelect && id !== "shopper" && id !== "internet";
          return (
            <g key={id}
              className={`node ${touched.has(id) ? "touched" : ""} ${isSource ? "source" : ""} ${isQuarantined ? "quarantined" : ""} ${clickable ? "clickable" : ""} ${selected === id ? "selected" : ""}`}
              transform={`translate(${node.x} ${node.y})`}
              {...(clickable ? {
                role: "button", tabIndex: 0, "aria-label": `${node.label} details`,
                onClick: () => onSelect(id),
                onKeyDown: (event: React.KeyboardEvent) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(id); } },
              } : {})}>
              {isSource && live && <circle r="40" className="pulse" />}
              <rect x="-54" y="-20" width="108" height="40" rx="10" />
              <text y="5" textAnchor="middle">{node.label}</text>
              {isQuarantined && <g transform="translate(46 -20)" className="lock"><circle r="11" /><path d="M-4,-1 h8 v6 h-8 z M-2.5,-1 v-3 a2.5,2.5 0 0 1 5,0 v3" /></g>}
            </g>
          );
        })}
      </svg>
      <div className="lab2-legend">
        <span className="ok">Allowed</span><span className="bad">Blocked by policy</span>
        {[...quarantined].map((id) => <span key={id} className="lock">{nodes[id]?.label ?? id} quarantined</span>)}
      </div>
    </div>
  );
}
