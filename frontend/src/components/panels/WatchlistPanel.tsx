"use client";

import { useState, useEffect, useCallback } from "react";
import { Plus, X, Star } from "lucide-react";
import { fetchInstruments, type InstrumentData } from "@/lib/api";
import type { TickData } from "@/hooks/useWebSocket";
import { formatPrice, pnlColor, cn } from "@/lib/utils";

interface WatchlistPanelProps {
  ticks: Record<string, TickData>;
  onSelect: (symbol: string, exchange: string) => void;
}

interface WatchItem {
  symbol: string;
  exchange: string;
  token: string;
}

const DEFAULT_WATCHLIST: WatchItem[] = [
  { symbol: "NIFTY", exchange: "NFO", token: "" },
  { symbol: "BANKNIFTY", exchange: "NFO", token: "" },
  { symbol: "GOLDM", exchange: "MCX", token: "" },
  { symbol: "SILVERM", exchange: "MCX", token: "" },
  { symbol: "COPPER", exchange: "MCX", token: "" },
  { symbol: "ALUMINIUM", exchange: "MCX", token: "" },
  { symbol: "ZINC", exchange: "MCX", token: "" },
  { symbol: "NATGASMINI", exchange: "MCX", token: "" },
  { symbol: "CRUDEOILM", exchange: "MCX", token: "" },
];

export function WatchlistPanel({ ticks, onSelect }: WatchlistPanelProps) {
  const [watchlist, setWatchlist] = useState<WatchItem[]>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("elder-watchlist");
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          // If saved list has equity stocks (old defaults), reset to futures-only
          const hasEquity = parsed.some((w: WatchItem) => w.exchange === "NSE");
          if (hasEquity) {
            localStorage.removeItem("elder-watchlist");
            return DEFAULT_WATCHLIST;
          }
          return parsed;
        } catch {}
      }
    }
    return DEFAULT_WATCHLIST;
  });
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<InstrumentData[]>([]);

  useEffect(() => {
    localStorage.setItem("elder-watchlist", JSON.stringify(watchlist));
  }, [watchlist]);

  useEffect(() => {
    if (!search || search.length < 2) { setResults([]); return; }
    const t = setTimeout(async () => {
      try {
        const res = await fetchInstruments("NSE", search, 10);
        setResults(res.instruments || []);
      } catch { setResults([]); }
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const addSymbol = (inst: InstrumentData) => {
    if (!watchlist.find((w) => w.symbol === inst.symbol && w.exchange === inst.exch_seg)) {
      setWatchlist([...watchlist, { symbol: inst.symbol, exchange: inst.exch_seg, token: inst.token }]);
    }
    setAdding(false);
    setSearch("");
  };

  const removeSymbol = (symbol: string) => {
    setWatchlist(watchlist.filter((w) => w.symbol !== symbol));
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <h3 className="text-xs font-semibold flex items-center gap-1">
          <Star className="w-3 h-3 text-amber" /> Watchlist
        </h3>
        <button
          onClick={() => setAdding(!adding)}
          className="p-0.5 hover:text-accent transition-colors"
        >
          {adding ? <X className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
        </button>
      </div>

      {adding && (
        <div className="px-3 py-2 border-b border-border">
          <input
            className="w-full bg-surface-2 border border-border rounded px-2 py-1 text-xs outline-none"
            placeholder="Search symbol..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />
          {results.length > 0 && (
            <div className="mt-1 max-h-32 overflow-y-auto">
              {results.map((inst) => (
                <button
                  key={inst.token}
                  className="w-full text-left px-2 py-1 text-[11px] hover:bg-accent/10 flex justify-between"
                  onClick={() => addSymbol(inst)}
                >
                  <span>{inst.symbol}</span>
                  <span className="text-muted">{inst.exch_seg}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {watchlist.map((item) => {
          const tick = ticks[item.token];
          const ltp = tick?.ltp;
          return (
            <button
              key={item.symbol}
              className="w-full flex items-center justify-between px-3 py-1.5 hover:bg-surface-2 transition-colors group text-[11px]"
              onClick={() => onSelect(item.symbol, item.exchange)}
            >
              <span className="font-medium">{item.symbol}</span>
              <div className="flex items-center gap-2">
                {ltp != null && (
                  <span className="font-mono">{formatPrice(ltp)}</span>
                )}
                <button
                  className="opacity-0 group-hover:opacity-100 text-muted hover:text-red transition-all"
                  onClick={(e) => { e.stopPropagation(); removeSymbol(item.symbol); }}
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
