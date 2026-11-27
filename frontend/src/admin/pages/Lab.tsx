import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeftRight, Bug, KeyRound, Server, CheckCircle2, ChevronDown, Crosshair, Lock, Network, Radar, RefreshCcw, RotateCcw, ShieldCheck, ShoppingCart, Upload, XCircle } from "lucide-react";
import HoldButton from "@/components/kokonutui/hold-button";
import type { AdminService, AdminSnapshot, LabRun, LabRunSummary, LabScenario, LabStatus, Scorecard } from "../adminService";
import { AreaChart } from "../charts";
import { errorText, useToaster } from "../toast";
import { Status, relative } from "../ui";
import { ADMIN_API } from "../../shop";
import { addEdge, ServiceMap, type MapEdge } from "../serviceMap";

/* Short, plain labels; the full description lives in the button tooltip. */
type Group = "normal" | "rules" | "model" | "check";
const GROUPS: Array<{ id: Group; title: string; note: string }> = [
  { id: "normal", title: "Normal activity", note: "Allowed traffic. Nothing should be flagged." },
  { id: "rules", title: "Stopped by the rules", note: "Blocked instantly; the AI then raises an incident." },
  { id: "model", title: "Allowed, but behaving oddly", note: "The rules allow the path, so the risk engine has to spot the unusual volume." },
  { id: "check", title: "Response checks", note: "Prove isolation and restore actually work." },
];
const BUTTONS: Record<string, { label: string; hint: string; icon: typeof Bug; tone: "go" | "attack" | "check"; group: Group }> = {
  "normal-checkout": { label: "Place an order", hint: "Real Northstar order through the cluster", icon: ShoppingCart, tone: "go", group: "normal" },
  "plugin-lateral-movement": { label: "Attack the other shop", hint: "Hacked plugin tries Bloom and shared services", icon: Bug, tone: "attack", group: "rules" },
  "bloom-attacks-northstar": { label: "Bloom attacks Northstar", hint: "Hacked Bloom API tries to get into Northstar", icon: ArrowLeftRight, tone: "attack", group: "rules" },
  "network-sweep": { label: "Network sweep", hint: "Plugin tries every service on the platform", icon: Network, tone: "attack", group: "rules" },
  "plugin-port-scan": { label: "Port scan", hint: "Plugin scans ports on the order API", icon: Radar, tone: "attack", group: "rules" },
  "data-exfiltration": { label: "Steal data out", hint: "Order API tries to send data outside the cluster", icon: Upload, tone: "attack", group: "rules" },
  "cloud-metadata": { label: "Steal cloud credentials", hint: "Plugin tries the instance-metadata address", icon: KeyRound, tone: "attack", group: "rules" },
  "reach-control-plane": { label: "Reach the Kubernetes API", hint: "Plugin dials the cluster API server", icon: Server, tone: "attack", group: "rules" },
  "plugin-valid-path-burst": { label: "Abuse valid access", hint: "Plugin floods the API it is allowed to use", icon: Crosshair, tone: "attack", group: "model" },
  "containment-check": { label: "Test quarantine", hint: "Prove the plugin is cut off, or restored", icon: ShieldCheck, tone: "check", group: "check" },
  "quarantine-restart": { label: "Restart quarantined plugin", hint: "New pod, same label: still cut off?", icon: RefreshCcw, tone: "check", group: "check" },
};
const ORDER = Object.keys(BUTTONS);


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
    const locked = data.security.incidents.filter((item) => item.status === "quarantined" || item.status === "review");
    const names = locked.map((item) => item.sourceName).join(", ");
    if (!window.confirm(`Reset the testbed?\n\n${locked.length ? `Unlock: ${names}\n` : ""}Close open alerts and clear earlier runs. Nothing is deleted.`)) return;
    try {
      for (const item of locked) {  // same audited, cluster-verified path an operator would use
        if (item.status === "quarantined") await service.respondToIncident(item.id, "review");
        await service.respondToIncident(item.id, "restore");
        say("allow", `restored ${item.sourceName}`);
      }
      setStatus(await service.resetLab());
      setRuns([]); setSelectedId(null); setRun(null); setActions([]);
      await refresh();
    } catch (reason) { say("error", errorText(reason, "Could not reset")); }
  }
  const ready = Boolean(status?.ready);
  const totals = runs.reduce((sum, item) => {
    const result = item.result;
    if (!result) return sum;
    sum.blocked += result.blocked_as_expected;
    sum.expected += result.expected_blocks;
    sum.unconfirmed += result.expected_blocks - result.blocked_as_expected;
    if (result.order_complete) sum.orders += 1;
    return sum;
  }, { blocked: 0, expected: 0, unconfirmed: 0, orders: 0 });

  return (
    <div className="lab2">
      <header className="lab2-head">
        <div><h1>Attack testbed</h1><p>Synthetic attacks inside the isolated lab. Not part of the production console.</p></div>
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

      <div className="lab3-stats">
        <div><strong>{runs.length}</strong><span>Runs this session</span></div>
        <div className="good"><strong>{totals.blocked}<small>/{totals.expected}</small></strong><span>Attacks blocked</span></div>
        <div className={totals.unconfirmed ? "bad" : ""}><strong>{totals.unconfirmed}</strong><span>Not confirmed blocked</span></div>
        <div><strong>{totals.orders}</strong><span>Orders placed</span></div>
      </div>

      <section className="lab3">
          <nav className="lab2-list lab3-list" aria-label="Scenarios">
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
                            <span className="lab2-row-text"><strong>{meta.label}</strong><small>{meta.hint}</small>
                              {scenario.mitre.length > 0 && <span className="lab2-mitre">{scenario.mitre.map((t) => <em key={t.id} title={`MITRE ATT&CK ${t.id}: ${t.name}`}>{t.id}</em>)}</span>}</span>
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
        <div className="lab3-center">
          <ServiceMap edges={edgesFor(run)} quarantined={new Set(plugin?.quarantined ? ["shipfast-plugin"] : [])} source={run?.evidence.source.name} live={live} />
          <Console run={run} actions={actions} live={live} />
        </div>
        <aside className="lab3-side">
          <Outcome run={run} live={live} incident={incident} quarantined={Boolean(plugin?.quarantined)} respond={respond} />
          <div className="lab3-runs">
            <h3>Recent runs</h3>
            {runs.length
              ? <ul className="lab2-history">
                  {runs.slice(0, 8).map((item) => (
                    <li key={item.id}><button className={item.id === selectedId ? "active" : ""} onClick={() => setSelectedId(item.id)}>
                      <span>{BUTTONS[item.scenario_id]?.label ?? item.title}</span>
                      <small>{relative(item.created_at)}</small>
                      <Verdict summary={item} />
                    </button></li>
                  ))}
                </ul>
              : <p>No runs yet. Pick a scenario on the left.</p>}
          </div>
        </aside>
      </section>

      {run && <Evidence run={run} />}

      <ScorecardPanel service={service} refreshKey={runs.length} />
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

function edgesFor(run: LabRun | null): MapEdge[] {
  if (!run) return [];
  const map = new Map<string, MapEdge>();
  // Draw only what Hubble actually observed; nothing matched yet means no edge.
  const source = run.evidence.source.name ?? "";
  for (const step of run.steps) {
    if (step.verdict) addEdge(map, source, step.target, step.verdict.forwarded, step.verdict.dropped);
    for (const hop of step.downstream ?? []) addEdge(map, hop.source, hop.destination, hop.forwarded, hop.dropped);
  }
  return [...map.values()];
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


/* Evaluation scorecard: computed on the server from recorded runs only. "Not measured" means no runs yet. */
function ScorecardPanel({ service, refreshKey }: { service: AdminService; refreshKey: number }) {
  const [card, setCard] = useState<Scorecard | null>(null);
  useEffect(() => { service.labScorecard().then(setCard).catch(() => undefined); }, [service, refreshKey]);
  if (!card) return null;
  const pct = (value: number | null) => (value === null ? "Not measured" : `${Math.round(value * 100)}%`);
  const secs = (value: number | null) => (value === null ? "Not measured" : `${value.toFixed(1)} s`);
  const tiles = [
    { label: "Prevention rate", value: pct(card.prevention_rate),
      note: `${card.prevention.blocked}/${card.prevention.expected} observed attempts dropped${card.prevention.unverified ? ` · ${card.prevention.unverified} unverified` : ""}${card.baseline_prevention_rate !== null ? ` · with SecureCloud off: ${pct(card.baseline_prevention_rate)}` : ""}` },
    { label: "Detection rate", value: pct(card.detection_rate), note: `${card.detection.detected}/${card.detection.attack_runs} attack runs` },
    { label: "False-positive rate", value: pct(card.false_positive_rate), note: `${card.false_positives.flagged}/${card.false_positives.benign_runs} normal runs flagged` },
    { label: "Time to detect", value: secs(card.time_to_detect_s), note: "median, run start to risk over threshold" },
    { label: "Containment time", value: secs(card.containment_time_s), note: `median of ${card.containments} verified isolation${card.containments === 1 ? "" : "s"}` },
    { label: "Policy overhead", value: card.overhead.delta_ms === null ? "Not measured" : `${card.overhead.delta_ms > 0 ? "+" : ""}${card.overhead.delta_ms} ms`,
      note: card.overhead.delta_ms === null ? "needs order runs with SecureCloud on and off" : `order round trip, on ${card.overhead.order_ms_on} ms vs off ${card.overhead.order_ms_off} ms` },
  ];
  return (
    <section className="lab3-score" aria-label="Evaluation scorecard">
      <header><h2>Evaluation scorecard</h2><p>From {card.runs} recorded run{card.runs === 1 ? "" : "s"} in the last 7 days. Nothing here is estimated.</p></header>
      <div className="lab3-score-grid">{tiles.map((tile) => (
        <div key={tile.label}><span>{tile.label}</span><strong>{tile.value}</strong><small>{tile.note}</small></div>))}</div>
    </section>
  );
}
