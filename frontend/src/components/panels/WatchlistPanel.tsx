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
  { symbol: "NIFTY", exchange: "NFO", token: "51714" },
  { symbol: "RELIANCE", exchange: "NSE", token: "2885" },
  { symbol: "HDFCBANK", exchange: "NSE", token: "1333" },
  { symbol: "INFY", exchange: "NSE", token: "1594" },
  { symbol: "TCS", exchange: "NSE", token: "11536" },
  { symbol: "SBIN", exchange: "NSE", token: "3045" },
  { symbol: "ITC", exchange: "NSE", token: "1660" },
];

export function WatchlistPanel({ ticks, onSelect }: WatchlistPanelProps) {
  const [watchlist, setWatchlist] = useState<WatchItem[]>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("elder-watchlist");
      if (saved) {
        try { return JSON.parse(saved); } catch {}
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
