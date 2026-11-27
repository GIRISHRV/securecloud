"""Live evaluation scorecard computed from recorded lab runs, detector windows and containment.

Every number comes from stored evidence; a metric with no supporting runs is reported as None
(not measured) rather than guessed. Definitions follow the project's evaluation criteria:

- prevention rate:   attempts observed DROPPED / attempts that should be blocked and were observed, with
                     SecureCloud on. Unobserved attempts are reported as "unverified", never as prevented
                     or failed. Runs with SecureCloud off form a separate baseline.
- detection rate:    attack runs whose source crossed the risk threshold within the run window
- false-positive rate: benign runs that produced a containment recommendation or an incident
- time to detect:    first window over the threshold minus run start (median, seconds)
- containment time:  incident opened -> quarantine verified in the cluster (median, seconds)
- policy overhead:   median order round trip with SecureCloud on vs off (benign checkout runs)
"""
from __future__ import annotations

import json
from statistics import median

from .scenarios import BY_ID

DETECTION_GRACE = 180.0  # detector windows can close shortly after the probes finish


def _median(values):
    return round(float(median(values)), 2) if values else None


def compute(store, since: float = 0.0) -> dict:
    with store.connect() as db:
        runs = [dict(row) for row in db.execute(
            "SELECT * FROM lab_runs WHERE status='completed' AND created_at>=? ORDER BY created_at", (since,))]
        risk = [dict(row) for row in db.execute(
            "SELECT source_id,window_end,accumulated_risk,threshold,response FROM risk_observations WHERE window_end>=?", (since,))]
        incidents = [dict(row) for row in db.execute("SELECT id,source_id,created_at FROM incidents WHERE created_at>=?", (since,))]
        contained = [dict(row) for row in db.execute(
            """SELECT c.completed_at,i.created_at FROM containment_requests c JOIN incidents i ON i.id=c.incident_id
               WHERE c.action='quarantine' AND c.status='succeeded' AND c.completed_at IS NOT NULL AND i.created_at>=?""", (since,))]

    blocked = expected = unverified = 0
    base_blocked = base_expected = 0
    attack_runs = detected = 0
    detect_times, rows = [], []
    benign_runs = false_positives = 0
    order_on, order_off = [], []
    for run in runs:
        scenario = BY_ID.get(run["scenario_id"])
        if scenario is None:
            continue
        result = json.loads(run["result_json"]) if run["result_json"] else {}
        start, end = run["started_at"] or run["created_at"], (run["finished_at"] or run["created_at"]) + DETECTION_GRACE
        windows = [r for r in risk if r["source_id"] == run["source_workload"] and start <= r["window_end"] <= end]
        over = sorted(r["window_end"] for r in windows if r["accumulated_risk"] >= r["threshold"])
        row = {"run": run["id"], "scenario": scenario.id, "title": scenario.title, "kind": scenario.kind,
               "mitre": [m[0] for m in scenario.mitre], "at": run["created_at"],
               "blocked": result.get("blocked_as_expected"), "expected_blocks": result.get("expected_blocks"),
               "detected": bool(over), "protection": result.get("protection")}
        if scenario.kind == "attack" and result.get("protection") is False:  # before/after baseline
            base_blocked += result.get("blocked_as_expected") or 0
            base_expected += max(0, (result.get("expected_blocks") or 0) - (result.get("inconclusive") or 0))
        elif scenario.kind == "attack":
            attack_runs += 1
            observed_expected = max(0, (result.get("expected_blocks") or 0) - (result.get("inconclusive") or 0))
            blocked += min(result.get("blocked_as_expected") or 0, observed_expected)
            expected += observed_expected
            unverified += min(result.get("inconclusive") or 0, result.get("expected_blocks") or 0)
            if over:
                detected += 1
                detect_times.append(over[0] - start)
        elif scenario.kind == "benign":
            benign_runs += 1
            flagged = any(r["response"] == "containment-recommended" for r in windows) or any(
                i["source_id"] == run["source_workload"] and start <= i["created_at"] <= end for i in incidents)
            row["false_positive"] = flagged
            false_positives += int(flagged)
            if result.get("order_ms") is not None:
                (order_on if result.get("protection", True) else order_off).append(result["order_ms"])
        rows.append(row)

    on, off = _median(order_on), _median(order_off)
    return {
        "runs": len(rows),
        "prevention_rate": round(blocked / expected, 4) if expected else None,
        "prevention": {"blocked": blocked, "expected": expected, "unverified": unverified},
        "baseline_prevention_rate": round(base_blocked / base_expected, 4) if base_expected else None,
        "detection_rate": round(detected / attack_runs, 4) if attack_runs else None,
        "detection": {"detected": detected, "attack_runs": attack_runs},
        "false_positive_rate": round(false_positives / benign_runs, 4) if benign_runs else None,
        "false_positives": {"flagged": false_positives, "benign_runs": benign_runs},
        "time_to_detect_s": _median(detect_times),
        "containment_time_s": _median([c["completed_at"] - c["created_at"] for c in contained]),
        "containments": len(contained),
        "overhead": {"order_ms_on": on, "order_ms_off": off, "runs_on": len(order_on), "runs_off": len(order_off),
                     "delta_ms": round(on - off, 2) if on is not None and off is not None else None},
        "recent": list(reversed(rows))[:12],
    }
