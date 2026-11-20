import { useState } from "react";
import { usePortal } from "../../app/PortalContext";
import { Icon, type IconName } from "../../components/Icon";
import { Badge } from "../../components/ui";
import { ActionButton } from "../../components/ActionButton";
import { DemoStageSurface } from "./DemoStageSurface";

type DemoStep = {
  title: string;
  short: string;
  icon: IconName;
  explanation: string;
  presenter: string;
};

const steps: readonly DemoStep[] = [
  {
    title: "Applications are running",
    short: "RetailCo and FacilitiesVendor",
    icon: "layers",
    explanation:
      "Two tenants run independent application stacks. RetailCo contains the storefront services; FacilitiesVendor contains a portal, maintenance API, and database.",
    presenter:
      "Start with the business applications. They work independently of the security console and their workload identities come from Kubernetes.",
  },
  {
    title: "Normal traffic is permitted",
    short: "Approved service paths",
    icon: "check",
    explanation:
      "Default deny is active, with narrow source, destination, and port intents for expected service communication. Hubble records forwarded traffic as positive evidence.",
    presenter:
      "Point out an allowed web-to-API or API-to-database connection. An allowed result is observed evidence, not an assumption based on policy configuration.",
  },
  {
    title: "Unexpected movement is blocked",
    short: "Vendor-to-retail denial",
    icon: "shield",
    explanation:
      "A compromised vendor workload attempts an unapproved RetailCo connection. Cilium enforces the policy and Hubble reports an explicit POLICY_DENIED verdict.",
    presenter:
      "Use the denied vendor-api to RetailCo row. This demonstrates prevention before the detector or response workflow is involved.",
  },
  {
    title: "Temporal risk is calculated",
    short: "GNN plus accumulated risk",
    icon: "activity",
    explanation:
      "The temporal graph engine scores the connection, accumulates source risk with EWMA, compares it with the edge-frequency baseline, and checks corroborating policy facts.",
    presenter:
      "Show the GNN, accumulated, baseline, and threshold columns. A high model score alone stays under observation; corroborated threshold crossings recommend response.",
  },
  {
    title: "The workload is contained",
    short: "Quarantine and investigation",
    icon: "alert",
    explanation:
      "An authorized operator can quarantine the source. The workload-scoped deny policy survives reconciliation and pod replacement while evidence remains available for review.",
    presenter:
      "Open the active incident and walk through Alert, Quarantined, Review, and Restored. Quarantine is the only live mutation in this walkthrough.",
  },
  {
    title: "Access is safely restored",
    short: "Policy state and evidence retained",
    icon: "refresh",
    explanation:
      "After review, restore removes the quarantine policy and returns the workload to its prior approved intents. The incident trace and triggering flows remain preserved.",
    presenter:
      "Finish with a restored incident and its complete trace. Then return to Network Map to confirm normal approved traffic is forwarded again.",
  },
];

const chain = [
  ["Applications", "Kubernetes workloads"],
  ["Enforcement", "Default deny + intents"],
  ["Detection", "Temporal graph risk"],
  ["Response", "Quarantine + restore"],
] as const;

export function DemoFlow() {
  const { data } = usePortal();
  const [selected, setSelected] = useState(0);
  const step = steps[selected];
  const retail = data.workloads.find(
    (workload) => workload.name === "frontend" && workload.previewUrl,
  );
  const vendor = data.workloads.find(
    (workload) => workload.name === "vendor-web" && workload.previewUrl,
  );
  const allowed = data.traffic.filter((event) => event.decision === "allowed").length;
  const denied = data.traffic.filter((event) => event.decision === "denied").length;
  const observations = data.security?.observations.length ?? 0;
  const active = data.incidents.filter((incident) => incident.status !== "restored").length;
  const restored = data.incidents.filter((incident) => incident.status === "restored").length;
  const evidence = [
    Boolean(retail && vendor),
    allowed > 0,
    denied > 0,
    observations > 0,
    active > 0,
    restored > 0,
  ];
  const evidenceCount = evidence.filter(Boolean).length;

  return (
    <div className="demo-flow-page">
      <section className="demo-flow-intro" aria-labelledby="demo-flow-heading">
        <div>
          <span className="demo-flow-eyebrow">Self-contained demonstration</span>
          <h2 id="demo-flow-heading">From workload traffic to recovery</h2>
          <p>
            Operate the applications, inspect enforcement and model evidence,
            and complete incident response without leaving this page.
          </p>
        </div>
        <div className="demo-flow-readiness" aria-label="Demo evidence readiness">
          <strong>{evidenceCount}/6</strong>
          <span>evidence stages ready</span>
          <Badge tone={evidenceCount === steps.length ? "green" : "amber"}>
            {evidenceCount === steps.length ? "Demo ready" : "Check evidence"}
          </Badge>
        </div>
      </section>

      <div className="demo-flow-chain" aria-label="SecureCloud processing flow">
        {chain.map(([title, detail], index) => (
          <div key={title}>
            <span>{index + 1}</span>
            <p><strong>{title}</strong><small>{detail}</small></p>
            {index < chain.length - 1 ? <Icon name="arrow" size={16} /> : null}
          </div>
        ))}
      </div>

      <div className="demo-flow-workspace">
        <nav className="demo-step-list" aria-label="Demo steps">
          {steps.map((item, index) => (
            <button
              key={item.title}
              className={selected === index ? "selected" : ""}
              aria-current={selected === index ? "step" : undefined}
              onClick={() => setSelected(index)}
            >
              <span className={evidence[index] ? "ready" : ""}>
                {evidence[index] ? <Icon name="check" size={13} /> : index + 1}
              </span>
              <p><strong>{item.title}</strong><small>{item.short}</small></p>
              <Icon name="chevron" size={14} />
            </button>
          ))}
        </nav>

        <section className="demo-step-detail" aria-live="polite">
          <header>
            <span className="demo-step-icon"><Icon name={step.icon} size={22} /></span>
            <div>
              <small>Step {selected + 1} of {steps.length}</small>
              <h2>{step.title}</h2>
            </div>
            <Badge tone={evidence[selected] ? "green" : "neutral"}>
              {evidence[selected] ? "Evidence ready" : "No evidence yet"}
            </Badge>
          </header>
          <div className="demo-step-copy">
            <div>
              <h3>What happens</h3>
              <p>{step.explanation}</p>
            </div>
            <div className="demo-presenter-note">
              <h3>What to say</h3>
              <p>{step.presenter}</p>
            </div>
          </div>
          <div className="demo-stage-surface">
            <DemoStageSurface selected={selected} />
          </div>
          <footer>
            <ActionButton
              className="button"
              disabled={selected === 0}
              onClick={() => setSelected((current) => Math.max(0, current - 1))}
            >
              Previous
            </ActionButton>
            <div>
              {selected < steps.length - 1 ? (
                <ActionButton
                  className="button primary"
                  onClick={() => setSelected((current) => current + 1)}
                >
                  Next step <Icon name="arrow" size={15} />
                </ActionButton>
              ) : (
                <ActionButton className="button primary" onClick={() => setSelected(0)}>
                  Restart walkthrough <Icon name="refresh" size={15} />
                </ActionButton>
              )}
            </div>
          </footer>
        </section>
      </div>

      <section className="demo-evidence-summary" aria-label="Live demo evidence summary">
        <div><span>Allowed flows</span><strong>{allowed}</strong></div>
        <div><span>Denied flows</span><strong>{denied}</strong></div>
        <div><span>Risk observations</span><strong>{observations}</strong></div>
        <div><span>Active incidents</span><strong>{active}</strong></div>
        <div><span>Restored incidents</span><strong>{restored}</strong></div>
      </section>
    </div>
  );
}
