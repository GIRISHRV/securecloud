import { describe, expect, it } from "vitest";
import type { RiskObservation } from "./models";
import { formatRiskScore, selectRiskEvidence } from "./riskEvidence";

const observation = (
  windowStart: number,
  anomalyScore: number,
  response: RiskObservation["response"] = "observe",
): RiskObservation => ({
  modelVersion: "test-model",
  windowStart,
  windowEnd: windowStart + 1,
  sourceId: "source",
  destinationId: `destination-${windowStart}`,
  sourceName: "source",
  destinationName: `destination-${windowStart}`,
  anomalyScore,
  accumulatedRisk: anomalyScore,
  baselineScore: 0.1,
  threshold: 0.5,
  corroborated: response === "containment-recommended",
  response,
  tenantId: "tenant",
});

describe("risk evidence presentation", () => {
  it("keeps the strongest finding beside recent observations", () => {
    const observations = [
      observation(1, 0.95, "containment-recommended"),
      ...Array.from({ length: 20 }, (_, index) =>
        observation(index + 2, 0.00012),
      ),
    ];

    const selected = selectRiskEvidence(observations, 6);

    expect(selected).toHaveLength(6);
    expect(selected[0].anomalyScore).toBe(0.95);
    expect(selected.some((item) => item.windowStart === 21)).toBe(true);
  });

  it("does not round small non-zero scores to zero", () => {
    expect(formatRiskScore(0.000147342)).toBe("0.000147");
    expect(formatRiskScore(0.5)).toBe("0.500");
  });
});
