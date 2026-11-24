import { useMemo, useState } from "react";
import type { AdminSnapshot } from "../adminService";
import { STATUS_LABEL } from "../analytics";
import { Avatar, Drawer, Empty, FilterInput, money, PageHead, Panel, relative, Status, Tabs, when } from "../ui";

type Filter = "all" | "online" | "repeat";

export function Customers({ data, query, setQuery, openOrder }: { data: AdminSnapshot; query: string; setQuery: (value: string) => void; openOrder: (id: string) => void }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const sessions = useMemo(() => new Map(data.sessions.map((session) => [session.user_id, session])), [data.sessions]);
  const online = data.customers.filter((customer) => sessions.get(customer.id)?.active).length;
  const repeat = data.customers.filter((customer) => customer.order_count > 1).length;
  const lifetime = data.customers.reduce((sum, customer) => sum + customer.total_spent_minor, 0);
  const filtered = data.customers
    .filter((customer) => filter === "all" || (filter === "online" ? sessions.get(customer.id)?.active : customer.order_count > 1))
    .filter((customer) => `${customer.display_name} ${customer.email} ${customer.phone}`.toLowerCase().includes(query.toLowerCase()))
    .sort((a, b) => b.total_spent_minor - a.total_spent_minor);
  const selected = data.customers.find((customer) => customer.id === selectedId) ?? null;
  const selectedOrders = selected ? data.orders.filter((order) => order.user_id === selected.id) : [];

  return (
    <>
      <PageHead title="Customers and sessions" description="Registered shoppers, lifetime value and current storefront sessions." />
      <div className="ad-kpis ad-kpis-compact">
        <div className="ad-kpi"><span className="ad-kpi-label">Customers</span><strong className="ad-kpi-value">{data.customers.length}</strong></div>
        <div className="ad-kpi"><span className="ad-kpi-label">Online now</span><strong className="ad-kpi-value">{online}</strong></div>
        <div className="ad-kpi"><span className="ad-kpi-label">Repeat buyers</span><strong className="ad-kpi-value">{data.customers.length ? Math.round((repeat / data.customers.length) * 100) : 0}%</strong></div>
        <div className="ad-kpi"><span className="ad-kpi-label">Lifetime revenue</span><strong className="ad-kpi-value">{money(lifetime)}</strong></div>
      </div>
      <div className="ad-toolbar">
        <Tabs label="Filter customers" value={filter} onChange={setFilter}
          options={[{ id: "all", label: "All", count: data.customers.length }, { id: "online", label: "Online", count: online }, { id: "repeat", label: "Repeat buyers", count: repeat }]} />
        <FilterInput label="Filter customers" value={query} onChange={setQuery} />
      </div>
      <Panel flush>
        {filtered.length
          ? <div className="ad-table-wrap"><table className="ad-table">
              <thead><tr><th>Customer</th><th>Phone</th><th className="ad-right">Orders</th><th className="ad-right">Total spent</th><th>Last seen</th><th>Session</th></tr></thead>
              <tbody>
                {filtered.map((customer) => {
                  const session = sessions.get(customer.id);
                  return (
                    <tr key={customer.id} className="ad-row-link" onClick={() => setSelectedId(customer.id)}>
                      <td><span className="ad-person"><Avatar name={customer.display_name} /><span>
                        <button className="ad-cell-link" onClick={(event) => { event.stopPropagation(); setSelectedId(customer.id); }}>{customer.display_name}</button>
                        <small>{customer.email}</small></span></span></td>
                      <td>{customer.phone || <span className="ad-muted">—</span>}</td>
                      <td className="ad-right ad-num">{customer.order_count}</td>
                      <td className="ad-right ad-num">{money(customer.total_spent_minor)}</td>
                      <td>{relative(customer.last_seen_at)}<small>Joined {new Date(customer.created_at * 1000).toLocaleDateString("en-IN", { month: "short", year: "numeric" })}</small></td>
                      <td><Status value={session?.active ? "active" : "offline"} label={session?.active ? "Online" : "Offline"} />{session && <small>{session.client_summary || "Browser session"}</small>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table></div>
          : <Empty title="No customers found">Customers appear here after they register in the storefront.</Empty>}
      </Panel>

      <Drawer open={Boolean(selected)} onClose={() => setSelectedId(null)} title={selected?.display_name ?? ""} subtitle={selected?.email}>
        {selected && (
          <div className="ad-detail">
            <div className="ad-profile"><Avatar name={selected.display_name} />
              <div><strong>{selected.display_name}</strong><small>Customer since {when(selected.created_at)}</small></div></div>
            <dl className="ad-facts ad-facts-grid">
              <div><dt>Orders</dt><dd>{selected.order_count}</dd></div>
              <div><dt>Total spent</dt><dd>{money(selected.total_spent_minor)}</dd></div>
              <div><dt>Average order</dt><dd>{money(selected.order_count ? Math.round(selected.total_spent_minor / selected.order_count) : 0)}</dd></div>
              <div><dt>Last seen</dt><dd>{relative(selected.last_seen_at)}</dd></div>
            </dl>
            <section>
              <h3>Order history</h3>
              {selectedOrders.length
                ? <ul className="ad-order-mini">
                    {selectedOrders.map((order) => (
                      <li key={order.id}><button onClick={() => openOrder(order.id)}>
                        <span><strong>{order.order_number}</strong><small>{when(order.created_at)}</small></span>
                        <Status value={order.status} label={STATUS_LABEL[order.status]} />
                        <strong className="ad-num">{money(order.total_minor)}</strong>
                      </button></li>
                    ))}
                  </ul>
                : <Empty title="No orders yet" />}
            </section>
          </div>
        )}
      </Drawer>
    </>
  );
}
