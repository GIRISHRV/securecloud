import { useMemo, useState } from "react";
import { Check, Download, MapPin, CreditCard, User } from "lucide-react";
import type { AdminService, AdminSnapshot, Order } from "../adminService";
import { NEXT_STATUS, STATUS_LABEL, STATUS_ORDER, statusCounts } from "../analytics";
import { Avatar, Drawer, Empty, FilterInput, money, PageHead, Panel, relative, Status, Tabs, when } from "../ui";
import { errorText, useToaster } from "../toast";

type Filter = "all" | "open" | Order["status"];
const PAGE = 25;

export function Orders({ data, service, query, setQuery, refresh, selectedId, select }: {
  data: AdminSnapshot; service: AdminService; query: string; setQuery: (value: string) => void; refresh: () => Promise<void>;
  selectedId: string | null; select: (id: string | null) => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [limit, setLimit] = useState(PAGE);
  const [busy, setBusy] = useState("");
  const toaster = useToaster();
  const counts = statusCounts(data.orders);
  const images = useMemo(() => new Map(data.products.map((product) => [product.id, product.image_path])), [data.products]);

  const filtered = data.orders.filter((order) =>
    (filter === "all" || (filter === "open" ? ["placed", "processing", "packing"].includes(order.status) : order.status === filter)) &&
    `${order.order_number} ${order.customer.name} ${order.customer.email} ${order.delivery_address.city} ${order.status}`.toLowerCase().includes(query.toLowerCase()));
  const selected = data.orders.find((order) => order.id === selectedId) ?? null;

  async function change(order: Order, status: Order["status"]) {
    if (status === order.status) return;
    setBusy(order.id);
    toaster.show(async () => {
      try { await service.updateOrderStatus(order.id, status); await refresh(); }
      finally { setBusy(""); }
    }, {
      loading: `Updating ${order.order_number}`,
      waiting: `${STATUS_LABEL[order.status]} → ${STATUS_LABEL[status]}`,
      success: [status === "cancelled" ? `${order.order_number} cancelled` : `${order.order_number} marked ${STATUS_LABEL[status].toLowerCase()}`, order.customer.name],
      error: (reason) => [`Could not update ${order.order_number}`, errorText(reason, "Try again")],
    });
  }

  function exportCsv() {
    const rows = [["order_number", "created_at", "customer", "email", "city", "status", "items", "total_inr"],
      ...filtered.map((order) => [order.order_number, new Date(order.created_at * 1000).toISOString(), order.customer.name, order.customer.email,
        order.delivery_address.city, order.status, String(order.items.reduce((sum, item) => sum + item.quantity, 0)), (order.total_minor / 100).toFixed(2)])];
    const csv = rows.map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(",")).join("\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    link.download = "northstar-orders.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  return (
    <>
      <PageHead title="Orders" description="Purchases, payments, delivery details and fulfilment.">
        <button className="ad-button" onClick={exportCsv} disabled={!filtered.length}><Download size={15} />Export CSV</button>
      </PageHead>
      <div className="ad-toolbar">
      <Tabs label="Filter orders by status" value={filter} onChange={(value) => { setFilter(value); setLimit(PAGE); }}
        options={[
          { id: "all", label: "All", count: data.orders.length },
          { id: "open", label: "Needs action", count: counts.placed + counts.processing + counts.packing },
          ...STATUS_ORDER.map((status) => ({ id: status as Filter, label: STATUS_LABEL[status], count: counts[status] })),
        ]} />
      <FilterInput label="Filter orders" value={query} onChange={setQuery} />
      </div>
      <Panel flush>
        {filtered.length
          ? <div className="ad-table-wrap"><table className="ad-table">
              <thead><tr><th>Order</th><th>Customer</th><th>Destination</th><th className="ad-right">Items</th><th className="ad-right">Total</th><th>Payment</th><th>Status</th></tr></thead>
              <tbody>
                {filtered.slice(0, limit).map((order) => (
                  <tr key={order.id} className={`ad-row-link ${order.id === selectedId ? "selected" : ""}`} onClick={() => select(order.id)}>
                    <td><button className="ad-cell-link" onClick={(event) => { event.stopPropagation(); select(order.id); }}>{order.order_number}</button><small>{when(order.created_at)}</small></td>
                    <td><span className="ad-person"><Avatar name={order.customer.name} /><span><span>{order.customer.name}</span><small>{order.customer.email}</small></span></span></td>
                    <td>{order.delivery_address.city}<small>{order.delivery_address.state}</small></td>
                    <td className="ad-right ad-num">{order.items.reduce((sum, item) => sum + item.quantity, 0)}</td>
                    <td className="ad-right ad-num">{money(order.total_minor)}</td>
                    <td><Status value={order.payment_status} label={order.payment_status === "paid" ? "Paid" : order.payment_status === "refunded" ? "Refunded" : "Failed"} /></td>
                    <td onClick={(event) => event.stopPropagation()}>
                      <select className="ad-select" aria-label={`Status for ${order.order_number}`} value={order.status}
                        disabled={busy === order.id || NEXT_STATUS[order.status].length === 0}
                        onChange={(event) => void change(order, event.target.value as Order["status"])}>
                        {[order.status, ...NEXT_STATUS[order.status]].map((status) => <option key={status} value={status}>{STATUS_LABEL[status]}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          : <Empty title="No orders found">Try a different status filter or search.</Empty>}
        {filtered.length > limit && (
          <div className="ad-more"><span>Showing {limit} of {filtered.length}</span><button className="ad-button" onClick={() => setLimit((value) => value + PAGE)}>Show more</button></div>
        )}
      </Panel>

      <Drawer open={Boolean(selected)} onClose={() => select(null)}
        title={selected?.order_number ?? ""} subtitle={selected ? `Placed ${when(selected.created_at)}` : undefined}
        footer={selected && NEXT_STATUS[selected.status].length > 0 && (
          <div className="ad-drawer-actions">
            {NEXT_STATUS[selected.status].map((status) => (
              <button key={status} className={`ad-button ${status === "cancelled" ? "ad-button-danger" : "ad-button-primary"}`}
                disabled={busy === selected.id} onClick={() => void change(selected, status)}>
                {status === "cancelled" ? "Cancel order" : `Mark as ${STATUS_LABEL[status].toLowerCase()}`}
              </button>
            ))}
          </div>
        )}>
        {selected && <OrderDetail order={selected} images={images} />}
      </Drawer>
    </>
  );
}

function OrderDetail({ order, images }: { order: Order; images: Map<string, string> }) {
  const steps: Order["status"][] = ["placed", "processing", "packing", "shipped", "delivered"];
  const current = steps.indexOf(order.status);
  return (
    <div className="ad-detail">
      <div className="ad-detail-status">
        <Status value={order.status} label={STATUS_LABEL[order.status]} />
        <span>Last updated {relative(order.updated_at)}</span>
      </div>
      {order.status === "cancelled"
        ? <p className="ad-inline-error">This order was cancelled. The simulated payment is marked refunded.</p>
        : <ol className="ad-steps">
            {steps.map((step, index) => (
              <li key={step} className={index < current ? "done" : index === current ? "current" : ""}>
                <span>{index <= current ? <Check size={11} /> : null}</span>{STATUS_LABEL[step]}
              </li>
            ))}
          </ol>}

      <section>
        <h3>Items</h3>
        <ul className="ad-lines">
          {order.items.map((item) => (
            <li key={item.id}>
              <span className="ad-thumb">{images.get(item.product_id) ? <img src={images.get(item.product_id)} alt="" /> : null}</span>
              <span className="ad-top-name"><strong>{item.name_snapshot}</strong><small>{item.sku_snapshot} · {money(item.unit_price_minor)} × {item.quantity}</small></span>
              <strong className="ad-num">{money(item.unit_price_minor * item.quantity)}</strong>
            </li>
          ))}
        </ul>
        <dl className="ad-facts ad-totals">
          <div><dt>Subtotal</dt><dd>{money(order.subtotal_minor)}</dd></div>
          <div><dt>Delivery</dt><dd>Free</dd></div>
          <div className="ad-total"><dt>Total</dt><dd>{money(order.total_minor)}</dd></div>
        </dl>
      </section>

      <section className="ad-detail-grid">
        <div>
          <h3><User size={14} aria-hidden="true" /> Customer</h3>
          <p><strong>{order.customer.name}</strong><br />{order.customer.email}<br />{order.customer.phone || "No phone"}</p>
        </div>
        <div>
          <h3><MapPin size={14} aria-hidden="true" /> Ship to</h3>
          <p>{order.delivery_address.recipient}<br />{order.delivery_address.line1}{order.delivery_address.line2 && <>, {order.delivery_address.line2}</>}<br />
            {order.delivery_address.city}, {order.delivery_address.state} {order.delivery_address.postal_code}</p>
        </div>
        <div>
          <h3><CreditCard size={14} aria-hidden="true" /> Payment</h3>
          <p><strong>{order.payment?.reference ?? "—"}</strong><br />Simulator · {when(order.payment?.created_at)}</p>
          <Status value={order.payment_status} label={order.payment_status === "paid" ? "Paid" : order.payment_status === "refunded" ? "Refunded" : "Failed"} />
        </div>
      </section>
    </div>
  );
}
