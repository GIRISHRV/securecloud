import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Pause, Play, Trash2, UserPlus } from "lucide-react";
import type { AdminService, Team, Usage } from "../adminService";
import { Empty, PageHead, Panel } from "../ui";
import { errorText } from "../toast";
import { SHOP } from "../../shop";

/* Shop owner settings: who can run the shop, how much of its isolated space it uses, and pause/resume. */

const LABELS: Record<string, string> = { pods: "Running containers", "requests.cpu": "CPU reserved", "requests.memory": "Memory reserved", "limits.cpu": "CPU limit", "limits.memory": "Memory limit" };

export function Settings({ service }: { service: AdminService }) {
  const [team, setTeam] = useState<Team | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [state, setState] = useState<string>("");
  const [email, setEmail] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    service.team(SHOP.id).then(setTeam).catch(() => undefined);
    if (!SHOP.fixed) service.ownerUsage(SHOP.id).then(setUsage).catch(() => setUsage({}));
    fetch(`/api/mall/shops/${encodeURIComponent(SHOP.id)}`).then((r) => r.json()).then((shop) => setState(shop.state)).catch(() => undefined);
  }, [service]);
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 5000); return () => window.clearInterval(timer); }, [load]);

  async function invite(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { await service.addMember(SHOP.id, email); setEmail(""); await load(); }
    catch (reason) { setError(errorText(reason, "Could not add that person")); }
    finally { setBusy(false); }
  }
  async function lifecycle(action: "pause" | "resume") {
    setBusy(true); setError("");
    try { await service.ownerLifecycle(SHOP.id, action, confirm); setConfirm(""); await load(); }
    catch (reason) { setError(errorText(reason, `Could not ${action} the shop`)); }
    finally { setBusy(false); }
  }
  const owner = team?.owner_is_you ?? false;

  return (
    <>
      <PageHead title="Settings" description="Your team, your isolated space on the cloud, and pausing the shop." />
      {error && <div className="ad-banner" role="alert"><strong>That did not work.</strong><span>{error}</span></div>}
      <div className="cn-tenants">
        <Panel title="Team" subtitle={owner ? "People you add can manage products and orders. Only you manage the team." : "Shop staff"}>
          {!team ? <Empty title="Loading" /> : (
            <div className="st-team">
              <ul>
                <li><strong>{owner ? "You" : "The owner"}</strong><small>Owner</small></li>
                {team.members.map((member) => (
                  <li key={member.user_id}>
                    <strong>{member.display_name}</strong><small>{member.email} · Staff</small>
                    {owner && <button className="ad-icon-button" aria-label={`Remove ${member.display_name}`} onClick={() => void service.removeMember(SHOP.id, member.user_id).then(load)}><Trash2 size={15} /></button>}
                  </li>
                ))}
              </ul>
              {owner && (
                <form className="st-invite" onSubmit={(event) => void invite(event)}>
                  <input type="email" required placeholder="name@example.com" value={email} onChange={(event) => setEmail(event.target.value)} aria-label="Email of the person to add" />
                  <button className="ad-button ad-button-primary" disabled={busy}><UserPlus size={15} />Add</button>
                </form>
              )}
            </div>
          )}
        </Panel>
        <Panel title="Your space" subtitle={SHOP.fixed ? "Testbed shops are managed by the provider." : "Your shop's own namespace, with fixed limits so one shop can't starve another."}>
          {SHOP.fixed ? <Empty title="Managed by the provider" /> : !usage ? <Empty title="Reading the cluster…" /> : Object.keys(usage).length === 0
            ? <Empty title="Usage unavailable" /> : (
              <ul className="st-usage">{Object.entries(usage).map(([key, value]) => {
                const n = (v: string) => v.endsWith("m") ? Number(v.slice(0, -1)) / 1000 : v.endsWith("Mi") ? Number(v.slice(0, -2)) / 1024 : v.endsWith("Gi") ? Number(v.slice(0, -2)) : Number(v);
                const ratio = Math.min(1, n(value.used) / Math.max(n(value.hard), 0.0001));
                return <li key={key}><span>{LABELS[key] ?? key}</span><i><b style={{ width: `${ratio * 100}%` }} /></i><small>{value.used} of {value.hard}</small></li>;
              })}</ul>
            )}
          {!SHOP.fixed && owner && (
            <div className="st-pause">
              <h3>{state === "paused" ? "Shop is paused" : "Pause the shop"}</h3>
              <p>{state === "paused" ? "Customers see that the shop is paused. Your data and security settings are kept." : "Stops your shop's services. Your data and security settings are kept."}</p>
              <label>Type <code>{SHOP.id}</code> to confirm<input value={confirm} onChange={(event) => setConfirm(event.target.value.trim())} spellCheck={false} /></label>
              {state === "paused"
                ? <button className="ad-button ad-button-primary" disabled={busy || confirm !== SHOP.id} onClick={() => void lifecycle("resume")}><Play size={15} />Resume shop</button>
                : <button className="ad-button" disabled={busy || confirm !== SHOP.id || state !== "live"} onClick={() => void lifecycle("pause")}><Pause size={15} />{state === "pausing" ? "Pausing…" : "Pause shop"}</button>}
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
