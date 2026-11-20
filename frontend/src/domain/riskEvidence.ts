import type { RiskObservation } from "./models";

const observationKey = (item: RiskObservation) =>
  `${item.modelVersion}:${item.windowStart}:${item.sourceId}:${item.destinationId}`;

/** Keep the strongest detector evidence visible beside recent normal traffic. */
export function selectRiskEvidence(
  observations: readonly RiskObservation[],
  limit = 10,
): RiskObservation[] {
  const strongest = [...observations].sort((left, right) => {
    const responseDifference =
      Number(right.response === "containment-recommended") -
      Number(left.response === "containment-recommended");
    return (
      responseDifference ||
      right.accumulatedRisk - left.accumulatedRisk ||
      right.anomalyScore - left.anomalyScore ||
      right.windowEnd - left.windowEnd
    );
  });
  const recent = [...observations].sort(
    (left, right) => right.windowEnd - left.windowEnd,
  );
  const selected = new Map<string, RiskObservation>();

  for (const item of strongest.slice(0, Math.min(4, limit))) {
    selected.set(observationKey(item), item);
  }
  for (const item of recent) {
    if (selected.size >= limit) break;
    selected.set(observationKey(item), item);
  }
  return [...selected.values()];
}

export function formatRiskScore(value: number): string {
  return value !== 0 && Math.abs(value) < 0.01
    ? value.toFixed(6)
    : value.toFixed(3);
}
