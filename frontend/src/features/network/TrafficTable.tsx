import type { TrafficEvent } from "../../domain/models";
import { reasonLabels } from "../../domain/policy";
import { Badge, Empty, time } from "../../components/ui";
import { usePortal } from "../../app/PortalContext";

export function TrafficTable({
  events,
  compact = false,
}: {
  events: TrafficEvent[];
  compact?: boolean;
}) {
  const { data } = usePortal();
  const tenantName = (id: string) =>
    data.tenants.find((t) => t.id === id)?.name ?? id;
  if (!events.length)
    return (
      <Empty title="No simulated traffic yet">
        Send a connection from the Network Map to see its policy decision here.
      </Empty>
    );
  return (
    <div
      className="table-scroll"
      role="region"
      aria-label="Simulated traffic events"
      tabIndex={0}
    >
      <table className="traffic-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Connection</th>
            <th>Decision</th>
            {!compact && <th>Reason</th>}
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.id}>
              <td className="mono muted">{time(event.at)}</td>
              <td>
                <div className="connection-names">
                  <strong>{event.sourceName}</strong>
                  <span aria-label="to">→</span>
                  <strong>{event.destinationName}</strong>
                </div>
                <small>
                  TCP {event.port} · {tenantName(event.sourceTenant)} →{" "}
                  {tenantName(event.destinationTenant)}
                </small>
              </td>
              <td>
                <Badge
                  tone={
                    event.decision === "allowed"
                      ? "green"
                      : event.decision === "denied"
                        ? "red"
                        : "amber"
                  }
                >
                  {event.decision}
                </Badge>
              </td>
              {!compact && (
                <td className="reason-cell">{reasonLabels[event.reason]}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
