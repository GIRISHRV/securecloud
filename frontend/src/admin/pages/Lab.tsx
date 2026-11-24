import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeftRight, Bug, CheckCircle2, ChevronDown, Crosshair, Lock, Network, Radar, RefreshCcw, RotateCcw, ShieldCheck, ShoppingCart, Upload, XCircle } from "lucide-react";
import HoldButton from "@/components/kokonutui/hold-button";
import type { AdminService, AdminSnapshot, LabRun, LabRunSummary, LabScenario, LabStatus } from "../adminService";
import { AreaChart } from "../charts";
import { errorText, useToaster } from "../toast";
import { Status, relative } from "../ui";
import { ADMIN_API } from "../../shop";

/* Short, plain labels; the full description lives in the button tooltip. */
type Group = "normal" | "rules" | "model" | "check";
const GROUPS: Array<{ id: Group; title: string; note: string }> = [
  { id: "normal", title: "Normal activity", note: "Allowed traffic. Nothing should be flagged." },
  { id: "rules", title: "Stopped by the rules", note: "Blocked instantly; the AI then raises an incident." },
  { id: "model", title: "Only the AI can catch", note: "The rules allow it, so only the AI model can flag it." },
  { id: "check", title: "Response checks", note: "Prove isolation and restore actually work." },
];
const BUTTONS: Record<string, { label: string; hint: string; icon: typeof Bug; tone: "go" | "attack" | "check"; group: Group }> = {
  "normal-checkout": { label: "Place an order", hint: "Real Northstar order through the cluster", icon: ShoppingCart, tone: "go", group: "normal" },
  "plugin-lateral-movement": { label: "Attack the other shop", hint: "Hacked plugin tries Bloom and shared services", icon: Bug, tone: "attack", group: "rules" },
  "bloom-attacks-northstar": { label: "Bloom attacks Northstar", hint: "Hacked Bloom API tries to get into Northstar", icon: ArrowLeftRight, tone: "attack", group: "rules" },
  "network-sweep": { label: "Network sweep", hint: "Plugin tries every service on the platform", icon: Network, tone: "attack", group: "rules" },
  "plugin-port-scan": { label: "Port scan", hint: "Plugin scans ports on the order API", icon: Radar, tone: "attack", group: "rules" },
  "data-exfiltration": { label: "Steal data out", hint: "Order API tries to send data outside the cluster", icon: Upload, tone: "attack", group: "rules" },
  "plugin-valid-path-burst": { label: "Abuse valid access", hint: "Plugin floods the API it is allowed to use", icon: Crosshair, tone: "attack", group: "model" },
  "containment-check": { label: "Test quarantine", hint: "Prove the plugin is cut off, or restored", icon: ShieldCheck, tone: "check", group: "check" },
  "quarantine-restart": { label: "Restart quarantined plugin", hint: "New pod, same label: still cut off?", icon: RefreshCcw, tone: "check", group: "check" },
};
const ORDER = Object.keys(BUTTONS);

/* Fixed map layout (viewBox 920 × 400). */
const NODES: Record<string, { x: number; y: number; label: string }> = {
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
};
const BASE_EDGES: Array<[string, string]> = [
  ["shopper", "northstar-web"], ["northstar-web", "northstar-api"], ["northstar-api", "northstar-database"],
  ["shipfast-plugin", "northstar-api"], ["bloom-web", "bloom-api"], ["bloom-api", "bloom-database"],
  ["northstar-api", "order-ids"], ["northstar-api", "payments"], ["northstar-api", "email"],
  ["bloom-api", "order-ids"], ["bloom-api", "payments"], ["bloom-api", "email"],
];

type Edge = { from: string; to: string; allowed: number; blocked: number };
const WALL_X = 636;

export function Lab({ data, service, refresh }: { data: AdminSnapshot; service: AdminService; refresh: () => Promise<void> }) {
  const toaster = useToaster();
  const [status, setStatus] = useState<LabStatus | null>(null);
  const [scenarios, setScenarios] = useState<LabScenario[]>([]);
  const [runs, setRuns] = useState<LabRunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [run, setRun] = useState<LabRun | null>(null);
  const [starting, setStarting] = useState("");
  const [actions, setActions] = useState<ConsoleLine[]>([]);
  const say = (kind: string, text: string) => setActions((lines) => [...lines.slice(-100), { at: Date.now() / 1000, kind, text }]);

  const loadOverview = useCallback(async () => {
    const fail = () => undefined;
    await Promise.all([
      service.labScenarios().then(setScenarios).catch(fail),
      service.labRuns().then((next) => { setRuns(next); setSelectedId((current) => current ?? next[0]?.id ?? null); }).catch(fail),
      service.labStatus().then((next) => { setStatus(next); if (next.running) setSelectedId(next.running); }).catch(fail),
    ]);
  }, [service]);
  useEffect(() => { void loadOverview(); const timer = window.setInterval(() => void loadOverview(), 5000); return () => window.clearInterval(timer); }, [loadOverview]);

  const live = run?.status === "queued" || run?.status === "running";
  useEffect(() => {
    if (!selectedId) { setRun(null); return; }
    let alive = true;
    const load = () => service.labRun(selectedId).then((next) => { if (alive) setRun(next); }).catch(() => undefined);
    void load();
    const timer = window.setInterval(load, live ? 400 : 3000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [selectedId, service, live]);

  async function start(scenario: LabScenario) {
    setStarting(scenario.id);
    try {
      const next = await service.startLabRun(scenario.id);
      setSelectedId(next.id); setRun(next); await loadOverview();
    } catch (reason) {
      toaster.show(() => Promise.reject(reason), { loading: "Starting", success: "", error: ["Could not start", errorText(reason, "Try again")] });
    } finally { setStarting(""); }
  }

  const incident = useMemo(() => {
    const open = run?.evidence.incidents.filter((item) => ["alert", "quarantined", "review"].includes(item.status)) ?? [];
    const id = (open.at(-1) ?? run?.evidence.incidents.at(-1))?.id;
    return data.security.incidents.find((item) => item.id === id) ?? null;
  }, [run, data.security.incidents]);

  async function respond(action: "quarantine" | "restore") {
    if (!incident) return;
    const call = async (step: "quarantine" | "review" | "restore") => {
      say("cmd", `POST ${ADMIN_API}/admin/security/incidents/${incident.id}/${step}`);
      try {
        const result = await service.respondToIncident(incident.id, step);
        say(step === "review" ? "out" : "allow", `${step} → ${result.status}${result.verified ? " · verified by Cilium policy read-back" : ""}`);
      } catch (reason) { say("error", `${step} failed: ${errorText(reason, "not verified")}`); throw reason; }
    };
    toaster.show(async () => {
      if (action === "quarantine") await call("quarantine");
      else {
        if (incident.status === "quarantined") await call("review");
        await call("restore");
      }
      await refresh(); await loadOverview();
    }, {
      loading: action === "quarantine" ? `Quarantining ${incident.sourceName}` : `Restoring ${incident.sourceName}`,
      success: action === "quarantine" ? [`${incident.sourceName} quarantined`, "Press “Test quarantine” to prove it"] : [`${incident.sourceName} restored`, "Previous access is back"],
      error: (reason) => ["Action failed", errorText(reason, "Not verified")],
    });
  }

  const plugin = status?.workloads["northstar-shop-stack/shipfast-plugin"];
  const protectedOn = status?.protection ?? true;
  const [switching, setSwitching] = useState(false);

  async function toggleProtection() {
    const next = !protectedOn;
    setSwitching(true);
    say("cmd", next ? "kubectl apply  default-deny + approved intents  (SecureCloud ON)" : "kubectl delete networkpolicy --all  (SecureCloud OFF)");
    try {
      setStatus(await service.setProtection(next));
      say(next ? "allow" : "drop", next ? "SecureCloud ON · tenant walls restored · detection running" : "SecureCloud OFF · no tenant walls · detection paused");
    } catch (reason) {
      say("error", errorText(reason, "Could not change protection"));
    } finally { setSwitching(false); }
  }

  async function resetDemo() {
    try {
      setStatus(await service.resetLab());
      setRuns([]); setSelectedId(null); setRun(null); setActions([]);
      await refresh();
    } catch (reason) { say("error", errorText(reason, "Could not reset")); }
  }
  const ready = Boolean(status?.ready);

  return (
    <div className="lab2">
      <header className="lab2-head">
        <div><h1>Live lab</h1><p>Click a scenario. Watch real traffic hit the cluster.</p></div>
        <div className="lab2-dots" aria-label="Lab status">
          <button className={`lab2-switch ${protectedOn ? "on" : "off"}`} role="switch" aria-checked={protectedOn}
            disabled={!ready || switching || Boolean(status?.running)} onClick={() => void toggleProtection()}
            title={protectedOn ? "Turn SecureCloud off to show the same attacks with no protection" : "Turn SecureCloud back on"}>
            <span className="knob" aria-hidden="true" />{switching ? "Switching…" : `SecureCloud ${protectedOn ? "ON" : "OFF"}`}
          </button>
          <button className="lab2-reset" onClick={() => void resetDemo()} disabled={Boolean(status?.running)} title="Hide earlier runs and incidents and start a clean demo">
            <RotateCcw size={14} aria-hidden="true" />Reset
          </button>
          <Dot ok={Boolean(status?.cluster.connected)} label="Cluster" />
          <Dot ok={Boolean(status?.telemetry.fresh)} label="Hubble" />
          <Dot ok={Boolean(status?.telemetry.detector)} label="AI model" />
        </div>
      </header>

      {status && !ready && <p className="lab2-offline">Lab is offline. Start it with <code>start.ps1</code>.</p>}
      {status && !protectedOn && <p className="lab2-unprotected"><strong>SecureCloud is OFF.</strong> No tenant walls and no detection: the cluster is flat, like a plain Kubernetes setup. Run the attacks to see what gets through.</p>}

      <section className="lab2-stage">
        <div className="lab2-board">
          <nav className="lab2-list" aria-label="Scenarios">
            <p className="lab2-list-title">Scenarios</p>
            {GROUPS.map((group) => {
              const items = [...scenarios]
                .filter((scenario) => (BUTTONS[scenario.id]?.group ?? "rules") === group.id)
                .sort((a, b) => ORDER.indexOf(a.id) - ORDER.indexOf(b.id));
              if (!items.length) return null;
              return (
                <section key={group.id} className={`lab2-group ${group.id}`} aria-label={group.title}>
                  <h4>{group.title}</h4>
                  <p>{group.note}</p>
                  <ul>
                    {items.map((scenario) => {
                      const meta = BUTTONS[scenario.id] ?? { label: scenario.title, hint: scenario.summary, icon: Bug, tone: "attack" as const, group: "rules" as const };
                      const Icon = meta.icon;
                      const active = run?.scenario_id === scenario.id;
                      const running = active && live;
                      return (
                        <li key={scenario.id}>
                          <button className={`lab2-row ${meta.tone} ${active ? "active" : ""}`} title={scenario.summary} aria-current={active || undefined}
                            disabled={!ready || Boolean(status?.running) || Boolean(starting)} onClick={() => void start(scenario)}>
                            <Icon className="lab2-row-icon" size={16} aria-hidden="true" />
                            <span className="lab2-row-text"><strong>{meta.label}</strong><small>{meta.hint}</small></span>
                            <span className="lab2-row-end" aria-hidden="true">{starting === scenario.id ? "Starting…" : running ? "Running…" : "›"}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
          </nav>
          <LiveMap run={run} quarantined={Boolean(plugin?.quarantined)} live={live} />
        </div>
        <Outcome run={run} live={live} incident={incident} quarantined={Boolean(plugin?.quarantined)} respond={respond} />
      </section>

      <Console run={run} actions={actions} live={live} />

      {run && <Evidence run={run} />}

      {runs.length > 0 && (
        <details className="lab2-fold">
          <summary><ChevronDown size={16} aria-hidden="true" />Past runs ({runs.length})</summary>
          <ul className="lab2-history">
            {runs.map((item) => (
              <li key={item.id}><button className={item.id === selectedId ? "active" : ""} onClick={() => setSelectedId(item.id)}>
                <span>{BUTTONS[item.scenario_id]?.label ?? item.title}</span>
                <small>{relative(item.created_at)}</small>
                <Verdict summary={item} />
              </button></li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Dot({ ok, label }: { ok: boolean; label: string }) {
  return <span className={`lab2-dot ${ok ? "ok" : "bad"}`}><i aria-hidden="true" />{label}</span>;
}

function Verdict({ summary }: { summary: LabRunSummary }) {
  if (summary.status === "failed") return <Status value="failed" label="Failed" />;
  if (!summary.result) return <Status value="processing" label="Running" />;
  if (summary.result.order_complete) return <Status value="succeeded" label="Order placed" />;
  if (summary.result.expected_blocks) return <Status value="succeeded" label={`${summary.result.blocked_as_expected}/${summary.result.expected_blocks} blocked`} />;
  return <Status value={summary.result.matched === summary.result.steps ? "succeeded" : "neutral"} label={`${summary.result.matched}/${summary.result.steps} as expected`} />;
}

function edgesFor(run: LabRun | null): Edge[] {
  if (!run) return [];
  const map = new Map<string, Edge>();
  const add = (from: string, to: string, allowed: number, blocked: number) => {
    // Draw only what Hubble actually observed; nothing matched yet means no edge.
    if (!NODES[from] || !NODES[to] || allowed + blocked === 0) return;
    const key = `${from}>${to}`;
    const edge = map.get(key) ?? { from, to, allowed: 0, blocked: 0 };
    edge.allowed += allowed; edge.blocked += blocked;
    map.set(key, edge);
  };
  const source = run.evidence.source.name ?? "";
  for (const step of run.steps) {
    if (step.verdict) add(source, step.target, step.verdict.forwarded, step.verdict.dropped);
    for (const hop of step.downstream ?? []) add(hop.source, hop.destination, hop.forwarded, hop.dropped);
  }
  return [...map.values()];
}

function line(from: string, to: string) {
  const a = NODES[from], b = NODES[to];
  return { x1: a.x, y1: a.y, x2: b.x, y2: b.y };
}

function LiveMap({ run, quarantined, live }: { run: LabRun | null; quarantined: boolean; live: boolean }) {
  const edges = edgesFor(run);
  const touched = new Set(edges.flatMap((edge) => [edge.from, edge.to]));
  const source = run?.evidence.source.name;
  return (
    <div className="lab2-map">
      <svg viewBox="0 0 920 530" role="img" aria-label="Service map with live connection verdicts">
        <rect className="zone retail" x="12" y="12" width="580" height="376" rx="16" />
        <text className="zone-label" x="30" y="38">Northstar (bags)</text>
        <rect className="zone vendor" x="680" y="12" width="228" height="376" rx="16" />
        <text className="zone-label" x="698" y="38">Bloom (candles)</text>
        <rect className="zone platform" x="12" y="408" width="896" height="112" rx="16" />
        <text className="zone-label" x="30" y="432">Mall platform (shared)</text>
        <line className="wall" x1="636" x2="636" y1="30" y2="182" /><line className="wall" x1="636" x2="636" y1="222" y2="370" />
        <text className="wall-label" x="636" y="206" textAnchor="middle">tenant wall</text>

        {BASE_EDGES.map(([from, to]) => <line key={`b-${from}-${to}`} className="edge-base" {...line(from, to)} />)}

        {edges.map((edge) => {
          const blocked = edge.blocked > 0 && edge.allowed === 0;
          const mixed = edge.blocked > 0 && edge.allowed > 0;
          const pts = line(edge.from, edge.to);
          // A blocked cross-tenant attempt stops at the tenant wall; other blocks stop halfway.
          const crosses = (pts.x1 - WALL_X) * (pts.x2 - WALL_X) < 0;
          const t = blocked && crosses ? (WALL_X - pts.x1) / (pts.x2 - pts.x1) : 0.5;
          const stop = { x: pts.x1 + (pts.x2 - pts.x1) * t, y: pts.y1 + (pts.y2 - pts.y1) * t };
          const end = blocked ? stop : { x: pts.x2, y: pts.y2 };
          const path = `M${pts.x1},${pts.y1} L${end.x},${end.y}`;
          const towardSource = pts.x1 > stop.x ? 1 : -1;
          return (
            <g key={`${edge.from}-${edge.to}`} className={blocked ? "edge blocked" : mixed ? "edge mixed" : "edge allowed"}>
              <line x1={pts.x1} y1={pts.y1} x2={end.x} y2={end.y} className="edge-line" />
              {[0, 0.3, 0.6].map((delay) => (
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
                {blocked ? `${edge.blocked} blocked` : mixed ? `${edge.blocked} blocked · ${edge.allowed} ok` : `${edge.allowed} ok`}
              </text>
            </g>
          );
        })}

        {Object.entries(NODES).map(([id, node]) => {
          const isSource = id === source;
          const isQuarantined = id === "shipfast-plugin" && quarantined;
          return (
            <g key={id} className={`node ${touched.has(id) ? "touched" : ""} ${isSource ? "source" : ""} ${isQuarantined ? "quarantined" : ""}`} transform={`translate(${node.x} ${node.y})`}>
              {isSource && live && <circle r="40" className="pulse" />}
              <rect x="-54" y="-20" width="108" height="40" rx="10" />
              <text y="5" textAnchor="middle">{node.label}</text>
              {isQuarantined && <g transform="translate(46 -20)" className="lock"><circle r="11" /><path d="M-4,-1 h8 v6 h-8 z M-2.5,-1 v-3 a2.5,2.5 0 0 1 5,0 v3" /></g>}
            </g>
          );
        })}
      </svg>
      <div className="lab2-legend"><span className="ok">Allowed</span><span className="bad">Blocked by policy</span>{quarantined && <span className="lock">ShipFast plugin quarantined</span>}</div>
    </div>
  );
}

function Outcome({ run, live, incident, quarantined, respond }: {
  run: LabRun | null; live: boolean; quarantined: boolean;
  incident: AdminSnapshot["security"]["incidents"][number] | null;
  respond: (action: "quarantine" | "restore") => Promise<void>;
}) {
  if (!run) return <aside className="lab2-outcome empty"><ShieldCheck size={36} aria-hidden="true" /><strong>Pick a scenario</strong><small>The result shows here.</small></aside>;
  const blocked = run.steps.reduce((sum, step) => sum + (step.verdict?.dropped ?? 0), 0);
  const allowed = run.steps.reduce((sum, step) => sum + (step.verdict?.forwarded ?? 0), 0);
  const peak = run.evidence.risk.reduce((max, item) => Math.max(max, item.accumulated_risk), 0);
  const threshold = run.evidence.risk.at(-1)?.threshold ?? 0.5;
  const isOrder = run.scenario_id === "normal-checkout";
  const isCheck = run.scenario_id === "containment-check" || run.scenario_id === "quarantine-restart";
  const isAttack = !isOrder && !isCheck;
  const flagged = run.evidence.risk.length > 0 && peak >= threshold;

  let headline = "Sending traffic…", sub = "", tone = "wait";
  if (run.status === "failed") { headline = "Run failed"; sub = run.error ?? ""; tone = "bad"; }
  else if (!live && blocked + allowed === 0) {
    // Never claim a block or a pass without a Hubble record.
    headline = "Not seen by Hubble"; sub = "No flow records matched. Check the telemetry dot."; tone = "warn";
  }
  else if (!live || blocked || allowed) {
    if (isOrder) { headline = run.result?.order_complete ? "Order placed" : allowed ? "Traffic allowed" : "No traffic seen"; sub = `${allowed} connections allowed`; tone = run.result?.order_complete ? "good" : "wait"; }
    else if (run.scenario_id === "plugin-valid-path-burst") { headline = `${allowed} allowed`; sub = flagged ? "AI flagged the pattern" : "Allowed path · AI did not flag it"; tone = "warn"; }
    else if (isCheck) { headline = blocked ? "Quarantine holds" : allowed ? "Access is open" : "No traffic seen"; sub = blocked ? `${blocked} attempts blocked` : `${allowed} connections allowed`; tone = blocked ? "good" : "warn"; }
    else { headline = `${blocked} blocked`; sub = `${allowed} got through`; tone = allowed ? "bad" : "good"; }
  }

  const stages = [
    { label: "Sent", done: Boolean(run.started_at) },
    { label: "Firewall", done: blocked + allowed > 0 },
    { label: "AI risk", done: run.evidence.risk.length > 0, alert: flagged },
    { label: "Incident", done: run.evidence.incidents.length > 0 && isAttack, alert: run.evidence.incidents.length > 0 && isAttack },
    { label: "Contained", done: quarantined },
  ];

  return (
    <aside className={`lab2-outcome ${tone}`}>
      <div className="lab2-headline">
        {tone === "good" ? <CheckCircle2 size={30} /> : tone === "bad" ? <XCircle size={30} /> : <Radar size={30} className={live ? "spin" : ""} />}
        <div><strong>{headline}</strong>{sub && <small>{sub}</small>}</div>
      </div>
      <ol className="lab2-stages">
        {stages.map((stage) => <li key={stage.label} className={`${stage.done ? "done" : ""} ${stage.alert ? "alert" : ""}`}><i />{stage.label}</li>)}
      </ol>
      {run.evidence.risk.length > 0 && (
        <div className="lab2-risk">
          <span>AI risk</span>
          <div className="lab2-meter"><b style={{ width: `${Math.min(100, peak * 100)}%` }} className={flagged ? "hot" : ""} /><i style={{ left: `${threshold * 100}%` }} /></div>
          <strong>{peak.toFixed(2)}</strong>
        </div>
      )}
      {isAttack && incident && incident.status === "alert" && (
        <HoldButton variant="red" holdDuration={1000} resetAfter={0} aria-label="Quarantine workload" className="lab2-hold"
          disabled={incident.finding?.response !== "containment-recommended"} holdingLabel="Keep holding…" completeLabel="Quarantined"
          onHoldComplete={() => void respond("quarantine")}>
          <Lock size={16} aria-hidden="true" /> Hold to quarantine
        </HoldButton>
      )}
      {quarantined && incident && (incident.status === "quarantined" || incident.status === "review") && (
        <button className="ad-button lab2-restore" onClick={() => void respond("restore")}>
          <RotateCcw size={15} aria-hidden="true" />Restore access
        </button>
      )}
    </aside>
  );
}

type ConsoleLine = { at: number; kind: string; text: string };

const PREFIX: Record<string, string> = { cmd: "$", send: "→", out: " ", allow: "✓", drop: "✕", hubble: "?", ai: "◆", incident: "!", info: "#", error: "✕" };

function Console({ run, actions, live }: { run: LabRun | null; actions: ConsoleLine[]; live: boolean }) {
  const body = useRef<HTMLDivElement>(null);
  const lines = useMemo(() => {
    if (!run) return actions;
    const since = (run.started_at ?? run.created_at) - 5;
    const source = run.evidence.source.name ?? "workload";
    const detector: ConsoleLine[] = run.evidence.risk.map((item) => ({
      at: item.window_end, kind: "ai",
      text: `${item.model_version}  ${source} → ${item.destination_name}  risk ${item.accumulated_risk.toFixed(2)} / ${item.threshold.toFixed(2)}  ${item.response === "containment-recommended" ? "CONTAINMENT RECOMMENDED" : "observe"}`,
    }));
    const incidents: ConsoleLine[] = run.evidence.incidents.map((item) => item.created_at >= since
      ? { at: item.created_at, kind: "incident", text: `incident opened  ${item.id}  ${item.reason}` }
      : { at: run.finished_at ?? run.created_at, kind: "incident", text: `evidence attached to open incident ${item.id} (${item.status})` });
    return [...run.log, ...detector, ...incidents, ...actions.filter((line) => line.at >= since)].sort((a, b) => a.at - b.at);
  }, [run, actions]);

  useEffect(() => { body.current?.scrollTo({ top: body.current.scrollHeight }); }, [lines.length]);

  return (
    <section className="lab2-console" aria-label="Lab console">
      <header><span className="lab2-console-dots" aria-hidden="true"><i /><i /><i /></span>securecloud lab console{run ? ` · ${run.id}` : ""}</header>
      <div ref={body} className="lab2-console-body" role="log" aria-live="polite">
        {lines.length === 0 && <p className="dim">Waiting for a scenario. Commands and results print here.</p>}
        {lines.map((line, index) => (
          <p key={`${line.at}-${index}`} className={`k-${line.kind}`}>
            <time>{new Date(line.at * 1000).toLocaleTimeString("en-IN", { hour12: false })}</time>
            <b>{PREFIX[line.kind] ?? "·"}</b>
            <span>{line.text}</span>
          </p>
        ))}
        {live && <p className="cursor"><time /><b>$</b><span /></p>}
      </div>
    </section>
  );
}

function Evidence({ run }: { run: LabRun }) {
  const risk = run.evidence.risk;
  return (
    <details className="lab2-fold">
      <summary><ChevronDown size={16} aria-hidden="true" />Show evidence</summary>
      <div className="lab2-evidence">
        <div className="ad-table-wrap"><table className="ad-table">
          <thead><tr><th>Connection</th><th>Expected</th><th>Seen by Hubble</th><th>Result</th></tr></thead>
          <tbody>{run.steps.map((step) => (
            <tr key={step.index}>
              <td><code>{run.evidence.source.name} → {step.target}:{step.port}</code></td>
              <td>{step.expect === "blocked" ? "Block" : "Allow"}</td>
              <td>{step.verdict ? `${step.verdict.dropped} blocked · ${step.verdict.forwarded} allowed` : "—"}<small>{step.verdict?.event_ids[0] ? `event ${step.verdict.event_ids[0].slice(0, 8)}…` : ""}</small></td>
              <td><Status value={step.state === "matched" ? "succeeded" : step.state === "unexpected" ? "failed" : "neutral"} label={step.state === "matched" ? "As expected" : step.state === "unexpected" ? "Unexpected" : step.state === "inconclusive" ? "Not seen" : "…"} /></td>
            </tr>
          ))}</tbody>
        </table></div>
        {risk.length > 1 && (
          <AreaChart ariaLabel="AI risk per connection" fixedMax={1} height={180} format={(value) => value.toFixed(2)}
            threshold={{ value: risk.at(-1)!.threshold, label: "alert line" }}
            points={risk.map((item) => ({ label: `→ ${item.destination_name}`, value: item.accumulated_risk, detail: `GNN ${item.anomaly_score.toFixed(2)}` }))} />
        )}
      </div>
    </details>
  );
}
