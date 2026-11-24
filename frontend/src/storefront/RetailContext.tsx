import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { RetailService, type Cart, type Order, type Product, type RetailUser } from "./retailService";

type RetailContextValue = {
  service: RetailService;
  user: RetailUser | null;
  products: Product[];
  cart: Cart | null;
  orders: Order[];
  loading: boolean;
  error: string;
  clearError: () => void;
  refreshCart: () => Promise<void>;
  refreshOrders: () => Promise<void>;
  acceptUser: (user: RetailUser | null) => Promise<void>;
};

const Context = createContext<RetailContextValue | null>(null);

export function RetailProvider({ children }: { children: ReactNode }) {
  const service = useMemo(() => new RetailService(), []);
  const [user, setUser] = useState<RetailUser | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [cart, setCart] = useState<Cart | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void Promise.all([service.products(), service.session()])
      .then(async ([loadedProducts, currentUser]) => {
        if (cancelled) return;
        setProducts(loadedProducts);
        setUser(currentUser);
        if (currentUser) {
          const [loadedCart, loadedOrders] = await Promise.all([service.cart(), service.orders()]);
          if (!cancelled) { setCart(loadedCart); setOrders(loadedOrders); }
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Storefront is unavailable");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [service]);

  async function refreshCart() { setCart(await service.cart()); }
  async function refreshOrders() { setOrders(await service.orders()); }
  async function acceptUser(next: RetailUser | null) {
    setUser(next);
    if (next) {
      const [nextCart, nextOrders] = await Promise.all([service.cart(), service.orders()]);
      setCart(nextCart); setOrders(nextOrders);
    } else { setCart(null); setOrders([]); }
  }

  return <Context.Provider value={{
    service, user, products, cart, orders, loading, error,
    clearError: () => setError(""), refreshCart, refreshOrders, acceptUser,
  }}>{children}</Context.Provider>;
}

export function useRetail() {
  const value = useContext(Context);
  if (!value) throw new Error("RetailProvider missing");
  return value;
}
