import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import fcose from "cytoscape-fcose";
import { Network, Workflow } from "lucide-react";

/*
 * Live service graph (Hubble/Kiali style). Built entirely from data: every tenant becomes a group,
 * every workload a node, every observed flow an edge coloured by its verdict. Nothing about the
 * topology is hardcoded, so new shops simply appear as new groups.
 */
cytoscape.use(fcose);

export type GraphService = { name: string; tenant: string; kind: "shop" | "platform" | "plugin"; calls: string[]; quarantined: boolean };
export type GraphFlow = { source: string; destination: string; allowed: number; blocked: number; recent: boolean };
export type GraphSelection = { node?: string; edge?: { source: string; destination: string } } | null;
type Layout = "force" | "layered";

const ROLE: Record<string, string> = { web: "Storefront", api: "Order API", database: "Orders DB" };
const pretty = (name: string) => name.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const label = (service: GraphService) => service.kind === "plugin"
  ? `${pretty(service.name.replace(/-plugin$/, "")).replace("Shipfast", "ShipFast")} plugin`
  : service.kind === "platform" ? pretty(service.name).replace("Order Ids", "Order IDs") : ROLE[service.name.split("-").pop() ?? ""] ?? pretty(service.name);

function elements(services: GraphService[], flows: GraphFlow[]): ElementDefinition[] {
  const out: ElementDefinition[] = [];
  const tenants = [...new Set(services.map((s) => s.tenant))];
  for (const tenant of tenants) {
    const platform = services.some((s) => s.tenant === tenant && s.kind === "platform");
    out.push({ data: { id: `tenant:${tenant}`, label: platform ? `${tenant} (shared)` : tenant }, classes: platform ? "zone platform" : "zone" });
  }
  const known = new Set(services.map((s) => s.name));
  for (const service of services) {
    out.push({ data: { id: service.name, label: label(service), parent: `tenant:${service.tenant}` },
      classes: ["service", service.kind, service.quarantined ? "quarantined" : ""].join(" ") });
  }
  const external = flows.some((f) => !known.has(f.destination));
  if (external) out.push({ data: { id: "internet", label: "Outside the cluster" }, classes: "service internet" });
  const seen = new Set<string>();
  for (const flow of flows) {
    const target = known.has(flow.destination) ? flow.destination : "internet";
    if (!known.has(flow.source)) continue;
    const verdict = flow.blocked && flow.allowed ? "mixed" : flow.blocked ? "blocked" : "allowed";
    const id = `${flow.source}>${target}`;
    seen.add(id);
    out.push({ data: { id, source: flow.source, target, verdict }, classes: `flow ${verdict} ${flow.recent ? "recent" : ""}` });
  }
  for (const service of services) {  // declared intents not used recently: faint, so the allow-list is visible
    for (const call of service.calls) {
      const id = `${service.name}>${call}`;
      if (known.has(call) && !seen.has(id)) out.push({ data: { id, source: service.name, target: call }, classes: "intent" });
    }
  }
  return out;
}

const STYLE: cytoscape.StylesheetJson = [
  { selector: "node.zone", style: { "background-color": "#f3f6fd", "background-opacity": 1, "border-width": 1.5, "border-color": "#d0d5dd",
    shape: "round-rectangle", label: "data(label)", "text-valign": "top", "text-halign": "center", "font-size": 13, "font-weight": 700,
    color: "#475467", padding: "18px", "text-margin-y": -6 } },
  { selector: "node.zone.platform", style: { "background-color": "#f2faf5", "border-color": "#a6f4c5" } },
  { selector: "node.service", style: { shape: "round-rectangle", width: 112, height: 38, "background-color": "#ffffff", "border-width": 1.5,
    "border-color": "#98a2b3", label: "data(label)", "font-size": 12, "font-weight": 600, color: "#344054", "text-valign": "center", "text-halign": "center" } },
  { selector: "node.plugin", style: { "border-style": "dashed", "border-color": "#b54708" } },
  { selector: "node.internet", style: { "background-color": "#f2f4f7", "border-style": "dotted" } },
  { selector: "node.quarantined", style: { "background-color": "#fef3f2", "border-color": "#f04438", "border-width": 3, color: "#b42318" } },
  { selector: "node.source", style: { "background-color": "#0f1728", color: "#ffffff", "border-color": "#0f1728" } },
  { selector: "node:selected", style: { "border-color": "#2f4fb3", "border-width": 3 } },
  { selector: "edge", style: { "curve-style": "bezier", "target-arrow-shape": "triangle", "arrow-scale": 0.9, width: 2.5 } },
  { selector: "edge.intent", style: { "line-color": "#d0d5dd", "target-arrow-color": "#d0d5dd", "line-style": "dashed", width: 1.5 } },
  { selector: "edge.allowed", style: { "line-color": "#12b76a", "target-arrow-color": "#12b76a" } },
  { selector: "edge.blocked", style: { "line-color": "#f04438", "target-arrow-color": "#f04438", "line-style": "dashed", "target-arrow-shape": "tee" } },
  { selector: "edge.mixed", style: { "line-color": "#f79009", "target-arrow-color": "#f79009" } },
  { selector: "edge.recent", style: { width: 3.5, "line-dash-pattern": [8, 6], "line-style": "dashed" } },
  { selector: "edge:selected", style: { width: 5, "overlay-opacity": 0.08 } },
];

export function GraphMap({ services, flows, source, selection, onSelect }: {
  services: GraphService[]; flows: GraphFlow[]; source?: string | null;
  selection: GraphSelection; onSelect: (selection: GraphSelection) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [layout, setLayout] = useState<Layout>("force");
  const data = useMemo(() => elements(services, flows), [services, flows]);
  const shape = useMemo(() => JSON.stringify(data.map((e) => e.data.id).sort()), [data]);

  useEffect(() => {
    if (!host.current) return;
    const instance = cytoscape({ container: host.current, style: STYLE, minZoom: 0.3, maxZoom: 2.2, wheelSensitivity: 0.25, boxSelectionEnabled: false });
    instance.on("tap", "node.service", (event) => onSelectRef.current({ node: event.target.id() }));
    instance.on("tap", "edge.flow", (event) => onSelectRef.current({ edge: { source: event.target.data("source"), destination: event.target.data("target") } }));
    instance.on("tap", (event) => { if (event.target === instance) onSelectRef.current(null); });
    cy.current = instance;
    let offset = 0;  // marching dashes on edges that carried traffic in the last 30 seconds
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const timer = reduced ? 0 : window.setInterval(() => { offset = (offset + 2) % 140; instance.edges(".recent").style("line-dash-offset", -offset); }, 60);
    return () => { window.clearInterval(timer); instance.destroy(); cy.current = null; };
  }, []);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // Structural change (new shop, new path): rebuild and lay out. Otherwise just restyle in place.
  useEffect(() => {
    const instance = cy.current;
    if (!instance) return;
    instance.batch(() => {
      instance.elements().remove();
      instance.add(data);
    });
    run(instance, layout);
  }, [shape, layout]);

  useEffect(() => {
    const instance = cy.current;
    if (!instance) return;
    instance.batch(() => {
      for (const element of data) {
        const existing = instance.getElementById(String(element.data.id));
        if (existing.nonempty()) existing.classes(element.classes as string);
      }
      instance.nodes().removeClass("source");
      if (source) instance.getElementById(source).addClass("source");
      instance.elements().unselect();
      if (selection?.node) instance.getElementById(selection.node).select();
      if (selection?.edge) instance.getElementById(`${selection.edge.source}>${selection.edge.destination}`).select();
    });
  }, [data, source, selection]);

  return (
    <div className="gm">
      <div className="gm-bar">
        <div className="gm-legend"><span className="ok">Allowed</span><span className="bad">Blocked</span><span className="intent">Allowed, unused</span>
          <span className="lock">Locked out</span></div>
        <div className="ad-segment" role="group" aria-label="Graph layout">
          <button className={layout === "force" ? "active" : ""} aria-pressed={layout === "force"} onClick={() => setLayout("force")}><Network size={14} />Force</button>
          <button className={layout === "layered" ? "active" : ""} aria-pressed={layout === "layered"} onClick={() => setLayout("layered")}><Workflow size={14} />Layered</button>
        </div>
      </div>
      <div ref={host} className="gm-canvas" role="img" aria-label="Live service graph: tenants, workloads and observed flows" />
    </div>
  );
}

function run(instance: Core, layout: Layout) {
  const options = layout === "force"
    ? { name: "fcose", animate: false, quality: "proof", nodeRepulsion: 9000, idealEdgeLength: 110, nestingFactor: 0.6, packComponents: true, padding: 24 }
    : { name: "breadthfirst", directed: true, spacingFactor: 1.05, padding: 24, animate: false };
  instance.layout(options as cytoscape.LayoutOptions).run();
  instance.fit(undefined, 24);
}
