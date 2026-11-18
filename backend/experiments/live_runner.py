"""Allowlisted live containment benchmark for the project-owned K3s lab."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean, median, stdev
from time import monotonic, sleep
import warnings
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from backend.infrastructure.base import WorkloadRequest
from backend.infrastructure.kubernetes import KubernetesInfrastructure

from .runner import PROJECT_TITLE


warnings.filterwarnings("ignore", message="Unverified HTTPS request")


@dataclass(frozen=True)
class Probe:
    success: bool
    status: int | None
    latency_ms: float
    error: str | None


@dataclass(frozen=True)
class LiveRun:
    repetition: int
    started_at: str
    positive_control: bool
    policy_observed: bool
    policy_apply_ms: float
    enforcement_observed: bool
    enforcement_latency_ms: float | None
    unrelated_requests: int
    unrelated_failures: int
    unrelated_disruption_rate: float
    unrelated_latency_before_ms: float
    unrelated_latency_during_ms: float
    unrelated_latency_delta_percent: float | None
    policy_remove_ms: float
    recovery_observed: bool
    recovery_latency_ms: float | None


def validate_loopback_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or not parsed.port
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Live probes must use an explicit loopback HTTP URL")
    return value.rstrip("/")


def probe(url: str, timeout: float = 2.0) -> Probe:
    started = monotonic()
    try:
        with urlopen(
            Request(url, headers={"User-Agent": "SecureCloud-Evaluation/1.0"}),
            timeout=timeout,
        ) as response:
            body = response.read(4_096)
            success = response.status == 200 and bool(body)
            return Probe(success, response.status, (monotonic() - started) * 1_000, None)
    except HTTPError as exc:
        return Probe(False, exc.code, (monotonic() - started) * 1_000, "HTTPError")
    except (URLError, TimeoutError, OSError) as exc:
        return Probe(False, None, (monotonic() - started) * 1_000, type(exc).__name__)


def wait_for(url: str, expected: bool, timeout_seconds: float = 15.0) -> tuple[bool, float]:
    started = monotonic()
    while monotonic() - started < timeout_seconds:
        if probe(url).success is expected:
            return True, (monotonic() - started) * 1_000
        sleep(0.2)
    return False, (monotonic() - started) * 1_000


def _mean_latency(url: str, samples: int) -> tuple[float, int]:
    observations = [probe(url) for _ in range(samples)]
    successful = [item.latency_ms for item in observations if item.success]
    return (mean(successful) if successful else 0.0), sum(not item.success for item in observations)


def distribution(values: list[float]) -> dict:
    if not values:
        raise ValueError("At least one observation is required")
    ordered = sorted(values)
    percentile_index = min(len(ordered) - 1, max(0, int(0.95 * len(ordered) + 0.999999) - 1))
    return {
        "n": len(ordered),
        "mean": mean(ordered),
        "median": median(ordered),
        "standard_deviation": stdev(ordered) if len(ordered) > 1 else 0.0,
        "p95": ordered[percentile_index],
        "min": ordered[0],
        "max": ordered[-1],
    }


def run_live_evaluation(
    *,
    output_dir: Path,
    kubeconfig: Path,
    api_server: str,
    school_url: str,
    hospital_url: str,
    repetitions: int = 30,
    latency_samples: int = 10,
) -> dict:
    if repetitions <= 0 or latency_samples <= 0:
        raise ValueError("Repetitions and latency samples must be positive")
    school = validate_loopback_url(school_url) + "/api/profile"
    hospital = validate_loopback_url(hospital_url) + "/api/profile"
    adapter = KubernetesInfrastructure(kubeconfig, api_server=api_server)
    adapter.health()
    workload = WorkloadRequest("college-api", "college", "college-api", "api")
    output_dir.mkdir(parents=True, exist_ok=True)
    runs: list[LiveRun] = []

    for repetition in range(repetitions):
        started_at = datetime.now(timezone.utc).isoformat()
        school_control = probe(school)
        hospital_control = probe(hospital)
        if not school_control.success or not hospital_control.success:
            raise RuntimeError("Positive controls failed; live measurements would be inconclusive")
        hospital_before, _ = _mean_latency(hospital, latency_samples)
        policy_started = monotonic()
        observation = None
        enforcement_observed = False
        enforcement_latency = None
        hospital_during = 0.0
        unrelated_failures = latency_samples
        restore_started = monotonic()
        try:
            observation = adapter.reconcile_quarantine(workload, True)
            policy_apply_ms = (monotonic() - policy_started) * 1_000
            enforcement_observed, enforcement_latency = wait_for(school, False)
            hospital_during, unrelated_failures = _mean_latency(hospital, latency_samples)
        finally:
            restore_started = monotonic()
            adapter.reconcile_quarantine(workload, False)
            policy_remove_ms = (monotonic() - restore_started) * 1_000
        recovery_observed, recovery_latency = wait_for(school, True, timeout_seconds=30.0)
        latency_delta = (
            ((hospital_during - hospital_before) / hospital_before) * 100
            if hospital_before > 0 and hospital_during > 0
            else None
        )
        runs.append(LiveRun(
            repetition=repetition,
            started_at=started_at,
            positive_control=True,
            policy_observed=bool(
                observation
                and observation.state == "quarantined"
                and observation.policy_uid
            ),
            policy_apply_ms=policy_apply_ms,
            enforcement_observed=enforcement_observed,
            enforcement_latency_ms=enforcement_latency if enforcement_observed else None,
            unrelated_requests=latency_samples,
            unrelated_failures=unrelated_failures,
            unrelated_disruption_rate=unrelated_failures / latency_samples,
            unrelated_latency_before_ms=hospital_before,
            unrelated_latency_during_ms=hospital_during,
            unrelated_latency_delta_percent=latency_delta,
            policy_remove_ms=policy_remove_ms,
            recovery_observed=recovery_observed,
            recovery_latency_ms=recovery_latency if recovery_observed else None,
        ))
        if not enforcement_observed or not recovery_observed:
            raise RuntimeError("Containment or recovery was not positively observed")

    rows = [asdict(run) for run in runs]
    with (output_dir / "live_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (output_dir / "live_runs.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    summary = {
        "project": PROJECT_TITLE,
        "scenario": "college_api_containment_cycle",
        "scope": "project-owned loopback K3s lab",
        "repetitions": repetitions,
        "positive_control_rate": sum(run.positive_control for run in runs) / repetitions,
        "policy_observation_rate": sum(run.policy_observed for run in runs) / repetitions,
        "enforcement_observation_rate": sum(run.enforcement_observed for run in runs) / repetitions,
        "recovery_observation_rate": sum(run.recovery_observed for run in runs) / repetitions,
        "mean_policy_apply_ms": mean(run.policy_apply_ms for run in runs),
        "mean_enforcement_latency_ms": mean(run.enforcement_latency_ms for run in runs if run.enforcement_latency_ms is not None),
        "mean_policy_remove_ms": mean(run.policy_remove_ms for run in runs),
        "mean_recovery_latency_ms": mean(run.recovery_latency_ms for run in runs if run.recovery_latency_ms is not None),
        "unrelated_service_disruption_rate": sum(run.unrelated_failures for run in runs) / sum(run.unrelated_requests for run in runs),
        "mean_unrelated_latency_delta_percent": mean(
            run.unrelated_latency_delta_percent
            for run in runs
            if run.unrelated_latency_delta_percent is not None
        ),
        "distributions": {
            "policy_apply_ms": distribution([run.policy_apply_ms for run in runs]),
            "enforcement_latency_ms": distribution([
                run.enforcement_latency_ms for run in runs
                if run.enforcement_latency_ms is not None
            ]),
            "policy_remove_ms": distribution([run.policy_remove_ms for run in runs]),
            "recovery_latency_ms": distribution([
                run.recovery_latency_ms for run in runs
                if run.recovery_latency_ms is not None
            ]),
            "unrelated_latency_delta_percent": distribution([
                run.unrelated_latency_delta_percent for run in runs
                if run.unrelated_latency_delta_percent is not None
            ]),
        },
        "limitations": [
            "Measures one-node local-lab policy reconciliation and HTTP observation.",
            "Does not infer denial from policy existence alone; positive controls bracket each run.",
            "CPU and memory overhead require a separate resource sampler and are not reported here.",
        ],
    }
    (output_dir / "live_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the allowlisted K3s containment benchmark")
    parser.add_argument("--output", type=Path, default=Path("runtime/experiments/live"))
    parser.add_argument("--kubeconfig", type=Path, default=Path("runtime/securecloud.kubeconfig"))
    parser.add_argument("--api-server", default="http://127.0.0.1:16443")
    parser.add_argument("--school-url", default="http://127.0.0.1:8091")
    parser.add_argument("--hospital-url", default="http://127.0.0.1:8092")
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--latency-samples", type=int, default=10)
    arguments = parser.parse_args()
    result = run_live_evaluation(
        output_dir=arguments.output,
        kubeconfig=arguments.kubeconfig,
        api_server=validate_loopback_url(arguments.api_server),
        school_url=arguments.school_url,
        hospital_url=arguments.hospital_url,
        repetitions=arguments.repetitions,
        latency_samples=arguments.latency_samples,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
