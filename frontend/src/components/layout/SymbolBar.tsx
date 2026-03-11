"use client";

import { useState, useEffect, useRef } from "react";
import { Search, X } from "lucide-react";
import { fetchInstruments, type InstrumentData } from "@/lib/api";
import { cn } from "@/lib/utils";

interface SymbolBarProps {
  symbol: string;
  exchange: string;
  interval: string;
  onSymbolChange: (symbol: string, exchange: string) => void;
  onIntervalChange: (interval: string) => void;
}

const INTERVALS = [
  { label: "1m", value: "1m" },
  { label: "5m", value: "5m" },
  { label: "15m", value: "15m" },
  { label: "1H", value: "1h" },
  { label: "1D", value: "1d" },
  { label: "1W", value: "1w" },
];

export function SymbolBar({
  symbol,
  exchange,
  interval,
  onSymbolChange,
  onIntervalChange,
}: SymbolBarProps) {
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<InstrumentData[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!search || search.length < 2) {
      setResults([]);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const res = await fetchInstruments(exchange, search, 20);
        setResults(res.instruments || []);
      } catch {
        setResults([]);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [search, exchange]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  return (
    <div className="flex items-center gap-3 px-4 py-1.5 border-b border-border bg-surface text-xs">
      {/* Symbol search */}
      <div ref={ref} className="relative">
        <div className="flex items-center gap-1.5 bg-surface-2 rounded px-2 py-1 border border-border">
          <Search className="w-3 h-3 text-muted" />
          <input
            className="bg-transparent outline-none w-32 text-foreground placeholder:text-muted"
            placeholder="Search symbol..."
            value={open ? search : symbol}
            onFocus={() => {
              setOpen(true);
              setSearch("");
            }}
            onChange={(e) => setSearch(e.target.value)}
          />
          {open && (
            <button onClick={() => { setOpen(false); setSearch(""); }}>
              <X className="w-3 h-3 text-muted" />
            </button>
          )}
        </div>

        {open && results.length > 0 && (
          <div className="absolute top-full left-0 mt-1 w-72 bg-surface-2 border border-border rounded shadow-lg z-50 max-h-64 overflow-y-auto">
            {results.map((inst) => (
              <button
                key={inst.token}
                className="w-full text-left px-3 py-1.5 hover:bg-accent/10 flex justify-between items-center"
                onClick={() => {
                  onSymbolChange(inst.display_symbol || inst.name, inst.exch_seg);
                  setOpen(false);
                  setSearch("");
                }}
              >
                <div className="flex flex-col">
                  <span className="font-medium">{inst.display_symbol || inst.symbol}</span>
                  <span className="text-[10px] text-muted">{inst.name}</span>
                </div>
                <span className="text-muted text-[10px]">{inst.exch_seg}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Exchange toggle */}
      <div className="flex items-center gap-1 bg-surface-2 rounded border border-border">
        {["NSE", "NFO", "MCX"].map((ex) => (
          <button
            key={ex}
            className={cn(
              "px-2 py-0.5 rounded text-[11px] font-medium transition-colors",
              exchange === ex
                ? "bg-accent text-white"
                : "text-muted hover:text-foreground"
            )}
            onClick={() => onSymbolChange(symbol, ex)}
          >
            {ex}
          </button>
        ))}
      </div>

      {/* Interval selector */}
      <div className="flex items-center gap-0.5 bg-surface-2 rounded border border-border">
        {INTERVALS.map((tf) => (
          <button
            key={tf.value}
            className={cn(
              "px-2 py-0.5 rounded text-[11px] font-medium transition-colors",
              interval === tf.value
                ? "bg-accent text-white"
                : "text-muted hover:text-foreground"
            )}
            onClick={() => onIntervalChange(tf.value)}
          >
            {tf.label}
          </button>
        ))}
      </div>

      {/* Current symbol display */}
      <span className="ml-auto font-mono text-foreground font-semibold">
        {symbol}:{exchange}
      </span>
    </div>
  );
}
