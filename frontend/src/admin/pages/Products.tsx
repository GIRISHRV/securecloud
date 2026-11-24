import { useEffect, useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
import type { AdminService, AdminSnapshot, Product } from "../adminService";
import { topProducts } from "../analytics";
import { Drawer, Empty, FilterInput, money, PageHead, Panel, Status } from "../ui";
import { errorText, useToaster } from "../toast";

const IMAGES = ["", "/products/backpack.webp", "/products/bottle.webp", "/products/lamp.webp", "/products/sunglasses.webp"];

export function Products({ data, service, query, setQuery, refresh, onLoadSample, loadingSample }: {
  data: AdminSnapshot; service: AdminService; query: string; setQuery: (value: string) => void; refresh: () => Promise<void>;
  onLoadSample: () => Promise<void>; loadingSample: boolean;
}) {
  const [busy, setBusy] = useState("");
  const toaster = useToaster();
  const [creating, setCreating] = useState(false);
  const sales = new Map(topProducts(data.orders, data.products, 30).map((entry) => [entry.id, entry]));
  const filtered = data.products.filter((product) => `${product.name} ${product.sku} ${product.description}`.toLowerCase().includes(query.toLowerCase()));
  const inventoryValue = data.products.reduce((sum, product) => sum + product.price_minor * product.stock_quantity, 0);

  async function patch(product: Product, changes: Partial<Pick<Product, "stock_quantity" | "published" | "price_minor">>) {
    setBusy(product.id);
    const previous = Object.fromEntries(Object.keys(changes).map((key) => [key, product[key as keyof typeof changes]])) as typeof changes;
    const what = "published" in changes ? (changes.published ? "Published" : "Hidden from storefront")
      : "price_minor" in changes ? `Price set to ${money(changes.price_minor ?? 0)}` : `Stock set to ${changes.stock_quantity}`;
    toaster.show(async () => {
      try { await service.updateProduct(product.id, changes); await refresh(); }
      finally { setBusy(""); }
    }, {
      loading: `Saving ${product.name}`,
      success: [what, product.name],
      error: (reason) => [`Could not save ${product.name}`, errorText(reason, "Try again")],
      undo: { run: async () => { await service.updateProduct(product.id, previous); await refresh(); }, success: ["Change undone", product.name] },
    });
  }

  return (
    <>
      <PageHead title="Products" description="Catalogue, pricing and inventory shown in the storefront.">
        <button className="ad-button" disabled={loadingSample} onClick={() => void onLoadSample()}>{loadingSample ? "Loading…" : "Load sample data"}</button>
        <button className="ad-button ad-button-primary" onClick={() => setCreating(true)}><Plus size={15} />Add product</button>
      </PageHead>
      <div className="ad-kpis ad-kpis-compact">
        <div className="ad-kpi"><span className="ad-kpi-label">Products</span><strong className="ad-kpi-value">{data.products.length}</strong></div>
        <div className="ad-kpi"><span className="ad-kpi-label">Published</span><strong className="ad-kpi-value">{data.products.filter((product) => product.published).length}</strong></div>
        <div className="ad-kpi"><span className="ad-kpi-label">Low or out of stock</span><strong className="ad-kpi-value">{data.products.filter((product) => product.stock_quantity <= 10).length}</strong></div>
        <div className="ad-kpi"><span className="ad-kpi-label">Inventory value</span><strong className="ad-kpi-value">{money(inventoryValue)}</strong></div>
      </div>
      <div className="ad-toolbar ad-toolbar-end"><FilterInput label="Filter products" value={query} onChange={setQuery} /></div>
      <Panel flush>
        {filtered.length
          ? <div className="ad-table-wrap"><table className="ad-table">
              <thead><tr><th>Product</th><th>Price</th><th>Inventory</th><th className="ad-right">Sold (30d)</th><th>Storefront</th></tr></thead>
              <tbody>{filtered.map((product) => (
                <ProductRow key={product.id} product={product} busy={busy === product.id} onPatch={patch}
                  sold={sales.get(product.id)?.units ?? 0} revenue={sales.get(product.id)?.revenue ?? 0} />
              ))}</tbody>
            </table></div>
          : <Empty title="No products yet" action={<button className="ad-button ad-button-primary" onClick={() => void onLoadSample()}>Load sample data</button>}>
              Load the sample catalogue or add your first product.</Empty>}
      </Panel>
      <Drawer open={creating} onClose={() => setCreating(false)} title="Add product" subtitle="New products appear in the storefront when published.">
        <NewProduct service={service} onDone={async () => { setCreating(false); await refresh(); }} />
      </Drawer>
    </>
  );
}

function ProductRow({ product, busy, onPatch, sold, revenue }: {
  product: Product; busy: boolean; sold: number; revenue: number;
  onPatch: (product: Product, changes: Partial<Pick<Product, "stock_quantity" | "published" | "price_minor">>) => Promise<void>;
}) {
  const [stock, setStock] = useState(String(product.stock_quantity));
  const [price, setPrice] = useState(String(product.price_minor / 100));
  useEffect(() => setStock(String(product.stock_quantity)), [product.stock_quantity]);
  useEffect(() => setPrice(String(product.price_minor / 100)), [product.price_minor]);
  const stockDirty = stock !== "" && Number(stock) !== product.stock_quantity;
  const priceDirty = price !== "" && Math.round(Number(price) * 100) !== product.price_minor;
  const level = Math.min(100, (product.stock_quantity / 60) * 100);
  return (
    <tr>
      <td><span className="ad-product-cell">
        <span className="ad-thumb ad-thumb-lg">{product.image_path ? <img src={product.image_path} alt="" /> : null}</span>
        <span><strong>{product.name}</strong><small>{product.sku} · {product.description}</small></span>
      </span></td>
      <td>
        <div className="ad-inline-edit">
          <span className="ad-prefix">₹</span>
          <input aria-label={`Price for ${product.name}`} type="number" min="0" step="1" value={price} onChange={(event) => setPrice(event.target.value)} />
          {priceDirty && <button className="ad-button ad-button-small" disabled={busy} onClick={() => void onPatch(product, { price_minor: Math.round(Number(price) * 100) })}>Save</button>}
        </div>
      </td>
      <td>
        <div className="ad-inline-edit">
          <input aria-label={`Stock for ${product.name}`} type="number" min="0" max="1000000" value={stock} onChange={(event) => setStock(event.target.value)} />
          <button className="ad-button ad-button-small" disabled={busy || !stockDirty} onClick={() => void onPatch(product, { stock_quantity: Number(stock) })}>Save</button>
        </div>
        <div className={`ad-meter ${product.stock_quantity === 0 ? "bad" : product.stock_quantity <= 10 ? "warn" : ""}`}><i style={{ width: `${level}%` }} /></div>
      </td>
      <td className="ad-right ad-num">{sold}<small>{money(revenue)}</small></td>
      <td>
        <button className={`ad-switch ${product.published ? "on" : ""}`} role="switch" aria-checked={product.published} disabled={busy}
          onClick={() => void onPatch(product, { published: !product.published })}>
          <span aria-hidden="true" />{product.published ? "Published" : "Hidden"}
        </button>
        {product.stock_quantity <= 10 && <div className="ad-gap-top"><Status value={product.stock_quantity ? "low" : "failed"} label={product.stock_quantity ? "Low stock" : "Out of stock"} /></div>}
      </td>
    </tr>
  );
}

function NewProduct({ service, onDone }: { service: AdminService; onDone: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [image, setImage] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    try {
      await service.createProduct({
        sku: String(form.get("sku")).toUpperCase(), name: String(form.get("name")), description: String(form.get("description")),
        price_minor: Math.round(Number(form.get("price")) * 100), stock_quantity: Number(form.get("stock")),
        published: form.get("published") === "on", image_path: image,
      });
      await onDone();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create product");
    } finally { setBusy(false); }
  }
  return (
    <form className="ad-form" onSubmit={(event) => void submit(event)}>
      <label>Name<input name="name" required minLength={2} maxLength={120} /></label>
      <label>SKU<input name="sku" required pattern="[A-Za-z0-9][A-Za-z0-9\-]{2,39}" placeholder="NS-ACC-040" /><small>Use NS-BAG, NS-ACC or NS-HOM to choose the storefront category.</small></label>
      <label>Description<textarea name="description" required minLength={2} maxLength={500} rows={3} /></label>
      <div className="ad-form-row">
        <label>Price (₹)<input name="price" type="number" min="0" step="1" required /></label>
        <label>Stock<input name="stock" type="number" min="0" max="1000000" required defaultValue={10} /></label>
      </div>
      <fieldset className="ad-image-picker">
        <legend>Image</legend>
        {IMAGES.map((src) => (
          <button type="button" key={src || "none"} className={image === src ? "active" : ""} onClick={() => setImage(src)} aria-pressed={image === src} aria-label={src ? src.split("/").pop() : "No image"}>
            {src ? <img src={src} alt="" /> : <span>None</span>}
          </button>
        ))}
      </fieldset>
      <label className="ad-check"><input type="checkbox" name="published" defaultChecked /> Publish to storefront</label>
      {error && <p className="ad-inline-error" role="alert">{error}</p>}
      <button className="ad-button ad-button-primary" disabled={busy}>{busy ? "Saving…" : "Create product"}</button>
    </form>
  );
}
