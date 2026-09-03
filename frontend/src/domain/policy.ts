import type { TrafficEvent, Workload } from "./models";
import { intentsForTenant } from "./seed";

export const WINDOW_MS = 60_000;
export const DENIAL_THRESHOLD = 3;
export const reasonLabels: Record<TrafficEvent["reason"], string> = {
  "approved-intent": "Approved tenant-local intent",
  "cross-tenant": "Cross-tenant access denied",
  "default-deny": "No matching intent · default deny",
  quarantine: "Quarantine overrides approved intents",
  unavailable: "Workload stopped · no policy result",
};

export function decide(
  source: Workload,
  destination: Workload,
  port: number,
): Pick<TrafficEvent, "decision" | "reason"> {
  // Unavailability is not evidence of enforcement, even for a quarantined workload.
  if (source.status !== "running" || destination.status !== "running")
    return { decision: "inconclusive", reason: "unavailable" };
  if (source.quarantined || destination.quarantined)
    return { decision: "denied", reason: "quarantine" };
  if (source.tenantId !== destination.tenantId)
    return { decision: "denied", reason: "cross-tenant" };
  const approved = intentsForTenant(source.tenantId).some(
    (intent) =>
      intent.tenantId === source.tenantId &&
      intent.source === source.templateId &&
      intent.destination === destination.templateId &&
      intent.port === port,
  );
  return approved
    ? { decision: "allowed", reason: "approved-intent" }
    : { decision: "denied", reason: "default-deny" };
}
