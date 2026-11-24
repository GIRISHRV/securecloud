"""Live lab harness: runs allowlisted scenarios in the project-owned K3s lab and
reports what SecureCloud actually observed.

Evidence rules (see AGENTS.md):
- A probe's own result (connected / timeout / refused) is the *client view*. It is
  shown, but never used as proof of enforcement.
- A step's verdict comes only from Hubble flow records ingested by the telemetry
  pipeline. No matching flow means "not observed", never "blocked".
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Callable

from backend.infrastructure.base import InfrastructureError
from backend.infrastructure.kubernetes import tenant_namespace

from .scenarios import BY_ID, PROBE_SCRIPT, SCENARIOS, Probe, Scenario

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_runs(
  id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, status TEXT NOT NULL,
  actor TEXT NOT NULL, created_at REAL NOT NULL, started_at REAL, finished_at REAL,
  source_workload TEXT, steps_json TEXT NOT NULL DEFAULT '[]', result_json TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS lab_runs_created_idx ON lab_runs(created_at DESC);
"""
OBSERVE_SECONDS = 8.0


class LabUnavailable(RuntimeError):
    pass


class LabService:
    def __init__(self, store, infrastructure, telemetry_status: dict, *, observe_seconds: float = OBSERVE_SECONDS,
                 clock: Callable[[], float] = time.time):
        self.store = store
        self.infrastructure = infrastructure
        self.telemetry = telemetry_status
        self.observe_seconds = observe_seconds
        self.clock = clock
        self.order_hook = None  # set by the retail router: places one real Northstar order
        self.session_start = clock()  # the provider console shows only this demo session
        self.protection = True  # SecureCloud enforcement and detection on/off for before/after demos
        self._lock = threading.Lock()
        self._logs: dict[str, list[dict]] = {}
        with store.connect() as db:
            db.executescript(SCHEMA)
            if "log_json" not in {row["name"] for row in db.execute("PRAGMA table_info(lab_runs)")}:
                db.execute("ALTER TABLE lab_runs ADD COLUMN log_json TEXT NOT NULL DEFAULT '[]'")
            db.execute(
                "UPDATE lab_runs SET status='failed', error='Interrupted by an API restart', finished_at=? "
                "WHERE status IN ('queued','running')",
                (clock(),),
            )

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        cluster = {"connected": False, "detail": "Kubernetes adapter is not configured"}
        if self.infrastructure is not None and hasattr(self.infrastructure, "exec_in_workload"):
            cached = getattr(self, "_health_cache", None)
            if cached and self.clock() - cached[0] < 5:
                cluster = cached[1]
            else:
                try:
                    cluster = {"connected": True, **self.infrastructure.health()}
                except Exception as exc:  # report, never raise
                    cluster = {"connected": False, "detail": str(exc) or type(exc).__name__}
                self._health_cache = (self.clock(), cluster)
        last_poll = self.telemetry.get("last_poll")
        telemetry = {
            "enabled": bool(self.telemetry.get("enabled")),
            "last_poll": last_poll,
            # Fresh means flows are actually arriving, not just that the collector is polling:
            # a stopped Hubble capture leaves the collector polling an idle file.
            "fresh": bool(last_poll and self.clock() - last_poll < 10 and not self.telemetry.get("last_error")
                          and self._newest_flow_age() < 15),
            "accepted": self.telemetry.get("accepted", 0),
            "detector": self.telemetry.get("detector"),
            "last_error": self.telemetry.get("last_error"),
        }
        workloads = {}
        for scenario in SCENARIOS:
            for stack, service in [(scenario.source_stack, scenario.source_service)] + [
                (probe.target_stack, probe.target_service) for probe in scenario.probes
            ]:
                row = self._workload(stack, service)
                workloads[f"{stack}/{service}"] = (
                    {"id": row["id"], "name": row["name"], "observed": row["observed"], "quarantined": bool(row["quarantined"])}
                    if row else None
                )
        ready = cluster["connected"] and telemetry["enabled"]
        return {"ready": ready, "cluster": cluster, "telemetry": telemetry, "workloads": workloads,
                "running": self._active_run_id(), "protection": self.protection, "session_start": self.session_start}

    def _newest_flow_age(self) -> float:
        with self.store.connect() as db:
            newest = db.execute("SELECT max(observed_at) FROM normalized_flows").fetchone()[0]
        return self.clock() - newest if newest else float("inf")

    def reset(self) -> dict:
        """Start a fresh demo session: earlier runs and incidents stay recorded but are hidden."""
        self.session_start = self.clock()
        return self.status()

    def set_protection(self, enabled: bool) -> dict:
        """Turn SecureCloud on or off for the lab tenants.

        Off removes every tenant network policy (so the cluster is flat, as without SecureCloud)
        and pauses graph detection; on re-applies default-deny and the approved intents.
        """
        if self.infrastructure is None or not hasattr(self.infrastructure, "set_protection"):
            raise LabUnavailable("The Kubernetes adapter is not configured.")
        if self._active_run_id():
            raise LabUnavailable("Wait for the running scenario to finish.")
        with self.store.connect() as db:
            tenants = [row[0] for row in db.execute(
                "SELECT DISTINCT tenant_id FROM stack_deployments WHERE desired!='deleted' AND stack_id IN ('northstar-shop-stack','bloom-shop-stack','platform-stack')")]
        self.infrastructure.set_protection(enabled, [tenant_namespace(tenant) for tenant in tenants])
        self.protection = enabled
        return self.status()

    def scenarios(self) -> list[dict]:
        return [
            {
                "id": s.id, "title": s.title, "kind": s.kind, "summary": s.summary,
                "what_to_watch": s.what_to_watch, "tags": list(s.tags),
                "source": s.source_service,
                "targets": sorted({p.target_service for p in s.probes}) or (["northstar-api"] if s.checkout else []),
            }
            for s in SCENARIOS
        ]

    # -------------------------------------------------------------------- runs
    def start(self, scenario_id: str, actor: str) -> dict:
        scenario = BY_ID.get(scenario_id)
        if scenario is None:
            raise KeyError(scenario_id)
        state = self.status()
        if not state["cluster"]["connected"]:
            raise LabUnavailable("The K3s lab is not reachable. Start the lab, then try again.")
        if not state["telemetry"]["enabled"]:
            raise LabUnavailable("Hubble telemetry is not configured, so verdicts could not be observed.")
        if not self._lock.acquire(blocking=False):
            raise LabUnavailable("Another lab scenario is still running.")
        try:
            source = self._workload(scenario.source_stack, scenario.source_service)
            if source is None:
                raise LabUnavailable(f"{scenario.source_service} is not deployed in the lab.")
            run_id = f"run-{uuid.uuid4().hex[:12]}"
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO lab_runs(id,scenario_id,status,actor,created_at,source_workload) VALUES(?,?,?,?,?,?)",
                    (run_id, scenario.id, "queued", actor, self.clock(), source["id"]),
                )
        except Exception:
            self._lock.release()
            raise
        threading.Thread(target=self._execute, args=(run_id, scenario, source), name=f"lab-{run_id}", daemon=True).start()
        return self.run(run_id)

    def runs(self, limit: int = 20) -> list[dict]:
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM lab_runs WHERE created_at>=? ORDER BY created_at DESC LIMIT ?",
                              (self.session_start, limit)).fetchall()
        return [self._summary(row) for row in rows]

    def run(self, run_id: str) -> dict | None:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM lab_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        detail = self._summary(row)
        detail["steps"] = json.loads(row["steps_json"])
        detail["result"] = json.loads(row["result_json"]) if row["result_json"] else None
        detail["evidence"] = self._evidence(row)
        detail["log"] = json.loads(row["log_json"] or "[]")
        return detail

    # --------------------------------------------------------------- internals
    def _active_run_id(self):
        with self.store.connect() as db:
            row = db.execute("SELECT id FROM lab_runs WHERE status IN ('queued','running') ORDER BY created_at DESC LIMIT 1").fetchone()
        return row["id"] if row else None

    def _workload(self, stack_id: str, service: str):
        with self.store.connect() as db:
            return db.execute(
                """SELECT w.* FROM workloads w JOIN stack_deployments s ON s.id=w.stack_deployment_id
                   WHERE s.stack_id=? AND w.name=? AND w.desired!='deleted' AND s.desired!='deleted'
                   ORDER BY s.created DESC LIMIT 1""",
                (stack_id, service),
            ).fetchone()

    def _log(self, run_id: str, kind: str, text: str):
        """Console line for the lab page: the real command sent and what came back."""
        lines = self._logs.setdefault(run_id, [])
        lines.append({"at": self.clock(), "kind": kind, "text": text})
        self._save(run_id, log_json=json.dumps(lines[-400:]))

    def _save(self, run_id: str, **fields):
        if "steps" in fields:
            fields["steps_json"] = json.dumps(fields.pop("steps"))
        if "result" in fields:
            fields["result_json"] = json.dumps(fields.pop("result"))
        columns = ",".join(f"{key}=?" for key in fields)
        with self.store.connect() as db:
            db.execute(f"UPDATE lab_runs SET {columns} WHERE id=?", (*fields.values(), run_id))

    def _execute(self, run_id: str, scenario: Scenario, source):
        started = self.clock()
        self._save(run_id, status="running", started_at=started)
        self._log(run_id, "info", f"scenario {scenario.id}: {scenario.title}")
        try:
            namespace = tenant_namespace(source["tenant_id"])
            if scenario.restart_source:
                self._restart(run_id, namespace, source)
            if scenario.checkout:
                steps, result = self._run_checkout(run_id, namespace, source)
            else:
                steps, result = self._run_probes(run_id, scenario, namespace, source)
            self._save(run_id, status="completed", finished_at=self.clock(), steps=steps, result=result)
            self._log(run_id, "info", f"run complete in {self.clock() - started:.1f}s · waiting for the detector to score the traffic")
        except (InfrastructureError, LabUnavailable, ValueError) as exc:
            self._log(run_id, "error", str(exc) or type(exc).__name__)
            self._save(run_id, status="failed", finished_at=self.clock(), error=str(exc) or type(exc).__name__)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Lab run %s failed", run_id)
            self._save(run_id, status="failed", finished_at=self.clock(), error=type(exc).__name__)
        finally:
            self._lock.release()

    def _target(self, probe: Probe):
        if probe.external_host:  # outside the cluster: no workload, Hubble sees the "world" identity
            return {"id": None, "tenant_id": None}, probe.external_host
        target = self._workload(probe.target_stack, probe.target_service)
        if target is None:
            raise LabUnavailable(f"{probe.target_service} is not deployed in the lab.")
        namespace = tenant_namespace(target["tenant_id"])
        host = (
            self.infrastructure.workload_pod_ip(namespace, target["id"])
            if probe.direct_pod_ip
            else f"{probe.target_service}.{namespace}.svc.cluster.local"
        )
        return target, host

    def _restart(self, run_id, namespace: str, source):
        self._log(run_id, "cmd", f"kubectl rollout restart -n {namespace} deploy/{source['name']}")
        old, new, seconds = self.infrastructure.restart_workload(namespace, source["id"], source["name"])
        self._log(run_id, "out", f"old pod {old} replaced by {new} in {seconds:.1f}s")
        self._log(run_id, "info", "same workload label → same policies (including any quarantine) apply to the new pod")

    def _run_probes(self, run_id, scenario: Scenario, namespace: str, source):
        quarantined = bool(source["quarantined"])
        steps, spec = [], []
        for index, probe in enumerate(scenario.probes):
            target, host = self._target(probe)
            expect = probe.expect
            if expect == "either":  # verification follows current containment state
                expect = "blocked" if quarantined else "allowed"
            steps.append({
                "index": index, "label": probe.label or probe.target_service, "target": probe.target_service,
                "target_id": target["id"], "cross_tenant": bool(target["tenant_id"]) and target["tenant_id"] != source["tenant_id"],
                "port": probe.port, "attempts": probe.count, "expect": expect, "state": "sending",
                "client": None, "verdict": None,
            })
            spec.append({"i": index, "host": host, "port": probe.port, "count": probe.count, "gap": probe.gap})
        self._save(run_id, steps=steps)
        self._log(run_id, "cmd", f"kubectl exec -n {namespace} deploy/{source['name']} -- python -c \"$PROBE\" '{json.dumps(spec, separators=(',', ':'))}'")
        for item in spec:
            self._log(run_id, "send", f"connect {item['host']}:{item['port']} ×{item['count']}")
        sent_at = self.clock()
        raw = self.infrastructure.exec_in_workload(namespace, source["id"], ["python", "-c", PROBE_SCRIPT, json.dumps(spec)])
        attempts = _last_json(raw)
        if not isinstance(attempts, list):
            raise ValueError("The lab probe did not return a result")
        hosts = {item["i"]: f"{item['host']}:{item['port']}" for item in spec}
        for item in attempts:
            self._log(run_id, "out", f"{hosts.get(item.get('i'), '?')}  {item['result']}  {item['ms']} ms")
        for step in steps:
            mine = [item for item in attempts if item.get("i") == step["index"]]
            step["client"] = {
                "connected": sum(1 for item in mine if item["result"] == "connected"),
                "failed": sum(1 for item in mine if item["result"] != "connected"),
                "results": sorted({item["result"] for item in mine}),
            }
            step["state"] = "observing"
        self._save(run_id, steps=steps)
        self._observe(run_id, steps, source["id"], sent_at)
        return steps, _score(steps)

    def _run_checkout(self, run_id, namespace: str, source):
        """A real Northstar order: saved by the shop, then sent web -> order API -> database in the cluster."""
        if self.order_hook is None:
            raise LabUnavailable("The Northstar storefront is not connected to the lab.")
        api = self._workload("northstar-shop-stack", "northstar-api")
        if api is None:
            raise LabUnavailable("The Northstar order API is not deployed in the lab.")
        steps = [{"index": 0, "label": "Shopper order", "target": "northstar-api", "target_id": api["id"],
                  "cross_tenant": False, "port": 8080, "attempts": 1, "expect": "allowed", "state": "sending",
                  "client": None, "verdict": None}]
        self._save(run_id, steps=steps)
        self._log(run_id, "cmd", "POST /api/retail/checkout  (customer@test.com, 1 item)")
        sent_at = self.clock()
        order, mirror = self.order_hook()
        self._log(run_id, "out", f"order saved  #{order['order_number']}  ₹{order['total_minor'] / 100:,.2f}")
        self._log(run_id, "send", f"POST {source['name']}/api/resources/orders  →  " + (
            f"{mirror['status']} in {mirror['ms']} ms" if mirror.get("ok") else f"failed: {mirror.get('error') or mirror.get('status')}"))
        platform = (mirror.get("record") or {}).get("platform") or {}
        if platform.get("order_id"):
            self._log(run_id, "out", f"platform  order id {platform['order_id']} · payment {platform.get('payment', '?')} · email {platform.get('email', '?')}")
        elif platform.get("error"):
            self._log(run_id, "error", f"platform settlement failed: {platform['error']}")
        steps[0]["client"] = {"order_id": order["order_number"], "complete": bool(mirror.get("ok")), "checkout": [],
                              "platform": platform}
        steps[0]["state"] = "observing"
        self._save(run_id, steps=steps)
        self._observe(run_id, steps, source["id"], sent_at, downstream_tenant=source["tenant_id"])
        result = _score(steps)
        result["order_id"] = order["order_number"]
        result["order_complete"] = bool(mirror.get("ok"))
        result["platform_order_id"] = platform.get("order_id")
        return steps, result

    def _observe(self, run_id, steps, source_id: str, sent_at: float, downstream_tenant: str | None = None):
        """Wait for Hubble flows that match each step; record only what was observed."""
        deadline = self.clock() + self.observe_seconds
        while True:
            flows = self.store.get_normalized_flows(start=sent_at - 2, limit=20_000)
            for step in steps:
                matched = [f for f in flows if f.source and f.source.workload_id == source_id
                           and (f.destination.workload_id == step["target_id"] if f.destination else step["target_id"] is None)
                           and (f.destination is not None or step["target_id"] is None)
                           and f.destination_port in (None, step["port"])]
                forwarded = [f for f in matched if f.verdict == "forwarded"]
                dropped = [f for f in matched if f.verdict == "dropped"]
                step["verdict"] = {
                    "forwarded": len(forwarded), "dropped": len(dropped),
                    "drop_reasons": sorted({f.drop_reason for f in dropped if f.drop_reason}),
                    "event_ids": [f.event_id for f in (dropped or forwarded)][:5],
                    "observed": "blocked" if dropped and not forwarded else "allowed" if forwarded else "not_observed",
                }
            if downstream_tenant:
                hops = {}
                for f in flows:
                    if f.source and f.destination and f.source.tenant_id == downstream_tenant:
                        key = (f.source.workload_name, f.destination.workload_name)
                        entry = hops.setdefault(key, {"source": key[0], "destination": key[1], "forwarded": 0, "dropped": 0})
                        entry["forwarded" if f.verdict == "forwarded" else "dropped"] += 1
                steps[0]["downstream"] = sorted(hops.values(), key=lambda item: (item["source"], item["destination"]))
            settled = not downstream_tenant or self.clock() - sent_at >= 3  # let downstream hops (platform calls) arrive
            if (settled and all(step["verdict"]["observed"] != "not_observed" for step in steps)) or self.clock() >= deadline:
                break
            self._save(run_id, steps=steps)
            time.sleep(0.4)
        source_name = next((w.workload_name for w in self.store.workload_identities() if w.workload_id == source_id), "source")
        for step in steps:
            verdict = step["verdict"]
            observed = verdict["observed"]
            step["state"] = "inconclusive" if observed == "not_observed" else "matched" if observed == step["expect"] else "unexpected"
            edge = f"{source_name} → {step['target']}:{step['port']}"
            if observed == "not_observed":
                self._log(run_id, "hubble", f"{edge}  no matching flow (not observed)")
            else:
                parts = [f"{verdict['dropped']} DROPPED" if verdict["dropped"] else "", f"{verdict['forwarded']} FORWARDED" if verdict["forwarded"] else ""]
                reason = f" ({', '.join(verdict['drop_reasons'])})" if verdict["drop_reasons"] else ""
                event = f"  event {verdict['event_ids'][0][:8]}" if verdict["event_ids"] else ""
                self._log(run_id, "drop" if observed == "blocked" else "allow", f"{edge}  {' · '.join(p for p in parts if p)}{reason}{event}")
        for hop in (steps[0].get("downstream") or [])[:12] if steps else []:
            if hop["source"] != source_name:
                self._log(run_id, "allow" if not hop["dropped"] else "drop", f"{hop['source']} → {hop['destination']}  {hop['forwarded']} FORWARDED" + (f" · {hop['dropped']} DROPPED" if hop["dropped"] else ""))
        self._save(run_id, steps=steps)

    def _summary(self, row) -> dict:
        scenario = BY_ID.get(row["scenario_id"])
        return {
            "id": row["id"], "scenario_id": row["scenario_id"], "title": scenario.title if scenario else row["scenario_id"],
            "kind": scenario.kind if scenario else None, "status": row["status"], "actor": row["actor"],
            "created_at": row["created_at"], "started_at": row["started_at"], "finished_at": row["finished_at"],
            "error": row["error"], "result": json.loads(row["result_json"]) if row["result_json"] else None,
        }

    def _evidence(self, row) -> dict:
        """Detection and response records for the run's source workload since the run began."""
        since = row["started_at"] or row["created_at"]
        until = (row["finished_at"] or self.clock()) + 120
        source = row["source_workload"]
        with self.store.connect() as db:
            risk = [dict(r) for r in db.execute(
                """SELECT model_version,window_start,window_end,source_id,destination_id,anomaly_score,accumulated_risk,
                          baseline_score,threshold,corroborated,response FROM risk_observations
                   WHERE source_id=? AND window_end>=? AND window_start<=? ORDER BY window_end""",
                (source, since - 30, until),
            )]
            # Incidents opened since the run began, plus any still-open case for this
            # workload (new findings attach to it rather than opening a duplicate).
            incidents = [dict(r) for r in db.execute(
                """SELECT id,status,reason,created_at,restored_at FROM incidents
                   WHERE source_id=? AND (created_at>=? OR id=(
                     SELECT id FROM incidents WHERE source_id=? AND status IN ('alert','quarantined','review')
                     ORDER BY created_at DESC LIMIT 1))
                   ORDER BY created_at""",
                (source, since - 5, source),
            )]
            workload = db.execute("SELECT name,quarantined FROM workloads WHERE id=?", (source,)).fetchone()
        names = {w.workload_id: w.workload_name for w in self.store.workload_identities()}
        for item in risk:
            item["destination_name"] = names.get(item["destination_id"], item["destination_id"])
            item["corroborated"] = bool(item["corroborated"])
        return {
            "source": {"id": source, "name": workload["name"] if workload else None,
                       "quarantined": bool(workload["quarantined"]) if workload else None},
            "risk": risk, "incidents": incidents,
        }


def _last_json(raw) -> object:
    """Parse the probe's LABRESULT line. The prefix stops the Kubernetes exec
    client from re-encoding JSON-looking output as a Python repr."""
    for line in reversed(str(raw or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("LABRESULT "):
            try:
                return json.loads(line[len("LABRESULT "):])
            except ValueError:
                return None
    return None


def _score(steps) -> dict:
    observed = [s for s in steps if s["verdict"] and s["verdict"]["observed"] != "not_observed"]
    expected_blocks = [s for s in steps if s["expect"] == "blocked"]
    return {
        "steps": len(steps),
        "observed": len(observed),
        "matched": sum(1 for s in steps if s["state"] == "matched"),
        "unexpected": sum(1 for s in steps if s["state"] == "unexpected"),
        "inconclusive": sum(1 for s in steps if s["state"] == "inconclusive"),
        "blocked_as_expected": sum(1 for s in expected_blocks if s["state"] == "matched"),
        "expected_blocks": len(expected_blocks),
    }
