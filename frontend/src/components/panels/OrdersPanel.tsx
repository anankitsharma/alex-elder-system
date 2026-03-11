"use client";

import { useEffect, useState, useCallback } from "react";
import { RefreshCw, XCircle } from "lucide-react";
import { fetchOrders, cancelOrder } from "@/lib/api";
import { formatPrice, cn } from "@/lib/utils";

interface Order {
  orderid?: string;
  tradingsymbol?: string;
  transactiontype?: string;
  ordertype?: string;
  quantity?: string;
  price?: string;
  status?: string;
  text?: string;
  updatetime?: string;
}

export function OrdersPanel() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchOrders();
      const data = res?.data;
      setOrders(Array.isArray(data) ? data : []);
      setError(res?.message && !res?.status ? res.message : null);
    } catch (e: any) {
      setError(e.message);
      setOrders([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);

  const handleCancel = async (orderId: string) => {
    try {
      await cancelOrder(orderId);
      load();
    } catch {}
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <h3 className="text-xs font-semibold">Orders</h3>
        <button
          onClick={load}
          disabled={loading}
          className="p-0.5 hover:text-accent transition-colors"
        >
          <RefreshCw className={cn("w-3 h-3", loading && "animate-spin")} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {error ? (
          <p className="text-xs text-amber p-3">{error}</p>
        ) : orders.length === 0 ? (
          <p className="text-xs text-muted p-3">No orders</p>
        ) : (
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-muted border-b border-border">
                <th className="text-left px-2 py-1 font-medium">Symbol</th>
                <th className="text-left px-2 py-1 font-medium">Side</th>
                <th className="text-right px-2 py-1 font-medium">Qty</th>
                <th className="text-right px-2 py-1 font-medium">Price</th>
                <th className="text-center px-2 py-1 font-medium">Status</th>
                <th className="px-2 py-1"></th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o, i) => {
                const isBuy = o.transactiontype === "BUY";
                const isPending = o.status === "open" || o.status === "pending";
                return (
                  <tr key={i} className="border-b border-border/50 hover:bg-surface-2">
                    <td className="px-2 py-1.5 font-medium">{o.tradingsymbol}</td>
                    <td className={cn("px-2 py-1.5 font-medium", isBuy ? "text-green" : "text-red")}>
                      {o.transactiontype}
                    </td>
                    <td className="text-right px-2 py-1.5 font-mono">{o.quantity}</td>
                    <td className="text-right px-2 py-1.5 font-mono">
                      {formatPrice(parseFloat(o.price || "0"))}
                    </td>
                    <td className="text-center px-2 py-1.5">
                      <span
                        className={cn(
                          "px-1.5 py-0.5 rounded text-[10px] font-medium",
                          o.status === "complete" && "bg-green/15 text-green",
                          o.status === "rejected" && "bg-red/15 text-red",
                          o.status === "cancelled" && "bg-muted/15 text-muted",
                          isPending && "bg-amber/15 text-amber"
                        )}
                      >
                        {o.status}
                      </span>
                    </td>
                    <td className="px-2 py-1.5">
                      {isPending && o.orderid && (
                        <button
                          onClick={() => handleCancel(o.orderid!)}
                          className="text-muted hover:text-red transition-colors"
                          title="Cancel order"
                        >
                          <XCircle className="w-3 h-3" />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
