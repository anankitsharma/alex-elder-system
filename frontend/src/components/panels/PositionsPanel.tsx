"use client";

import { useEffect, useState, useCallback } from "react";
import { RefreshCw, TrendingUp, TrendingDown } from "lucide-react";
import { fetchPositions } from "@/lib/api";
import { formatPrice, formatPnl, pnlColor, cn } from "@/lib/utils";

interface Position {
  tradingsymbol?: string;
  symbolname?: string;
  exchange?: string;
  producttype?: string;
  netqty?: string;
  buyavgprice?: string;
  sellavgprice?: string;
  ltp?: string;
  pnl?: string;
}

export function PositionsPanel() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchPositions();
      const data = res?.data;
      setPositions(Array.isArray(data) ? data : []);
      setError(res?.message && !res?.status ? res.message : null);
    } catch (e: any) {
      setError(e.message);
      setPositions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [load]);

  const totalPnl = positions.reduce(
    (sum, p) => sum + parseFloat(p.pnl || "0"),
    0
  );

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <h3 className="text-xs font-semibold">Positions</h3>
        <div className="flex items-center gap-2">
          {positions.length > 0 && (
            <span className={cn("text-xs font-mono font-semibold", pnlColor(totalPnl))}>
              {formatPnl(totalPnl)}
            </span>
          )}
          <button
            onClick={load}
            disabled={loading}
            className="p-0.5 hover:text-accent transition-colors"
          >
            <RefreshCw className={cn("w-3 h-3", loading && "animate-spin")} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {error ? (
          <p className="text-xs text-amber p-3">{error}</p>
        ) : positions.length === 0 ? (
          <p className="text-xs text-muted p-3">No open positions</p>
        ) : (
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-muted border-b border-border">
                <th className="text-left px-2 py-1 font-medium">Symbol</th>
                <th className="text-right px-2 py-1 font-medium">Qty</th>
                <th className="text-right px-2 py-1 font-medium">LTP</th>
                <th className="text-right px-2 py-1 font-medium">P&L</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => {
                const qty = parseInt(p.netqty || "0");
                const pnl = parseFloat(p.pnl || "0");
                return (
                  <tr key={i} className="border-b border-border/50 hover:bg-surface-2">
                    <td className="px-2 py-1.5">
                      <div className="flex items-center gap-1">
                        {qty > 0 ? (
                          <TrendingUp className="w-3 h-3 text-green" />
                        ) : qty < 0 ? (
                          <TrendingDown className="w-3 h-3 text-red" />
                        ) : null}
                        <span className="font-medium">
                          {p.tradingsymbol || p.symbolname}
                        </span>
                      </div>
                    </td>
                    <td className="text-right px-2 py-1.5 font-mono">{qty}</td>
                    <td className="text-right px-2 py-1.5 font-mono">
                      {formatPrice(parseFloat(p.ltp || "0"))}
                    </td>
                    <td className={cn("text-right px-2 py-1.5 font-mono font-medium", pnlColor(pnl))}>
                      {formatPnl(pnl)}
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
