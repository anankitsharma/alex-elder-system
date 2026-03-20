"use client";

import { useState, useEffect, useRef } from "react";
import { useTradingStore } from "@/store/useTradingStore";
import { cn } from "@/lib/utils";
import { Search, X } from "lucide-react";

interface Props {
  open: boolean;
  onClose: () => void;
  onSelect: (symbol: string, exchange: string) => void;
}

export default function SymbolSearch({ open, onClose, onSelect }: Props) {
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const assets = useTradingStore((s) => s.commandCenterAssets);

  const filtered = query.trim()
    ? assets.filter((a) =>
        a.symbol.toLowerCase().includes(query.toLowerCase()) ||
        a.exchange.toLowerCase().includes(query.toLowerCase())
      )
    : assets;

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIdx(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    setSelectedIdx(0);
  }, [query]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && filtered[selectedIdx]) {
      onSelect(filtered[selectedIdx].symbol, filtered[selectedIdx].exchange);
      onClose();
    } else if (e.key === "Escape") {
      onClose();
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
      <div
        className="relative w-[500px] rounded-xl border border-border bg-surface shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
          <Search className="w-4 h-4 text-muted" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search symbol... (↑↓ navigate, Enter select)"
            className="flex-1 bg-transparent text-foreground text-sm outline-none placeholder:text-muted"
          />
          <button onClick={onClose} className="p-1 rounded hover:bg-surface-2">
            <X className="w-3.5 h-3.5 text-muted" />
          </button>
        </div>

        {/* Results */}
        <div className="max-h-[300px] overflow-auto">
          {filtered.length === 0 ? (
            <div className="text-center text-muted text-sm py-6">No matches</div>
          ) : (
            filtered.map((a, i) => {
              const al = a.alignment;
              const isUp = (a.change_pct ?? 0) >= 0;
              return (
                <div
                  key={`${a.symbol}:${a.exchange}`}
                  onClick={() => { onSelect(a.symbol, a.exchange); onClose(); }}
                  className={cn(
                    "flex items-center justify-between px-4 py-2.5 cursor-pointer transition-colors",
                    i === selectedIdx ? "bg-accent/10" : "hover:bg-surface-2"
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-foreground text-sm">{a.symbol}</span>
                    <span className="text-[9px] text-muted px-1 py-0.5 rounded bg-surface-2">{a.exchange}</span>
                    {a.grade && (
                      <span className={cn("text-[9px] px-1 py-0.5 rounded font-bold",
                        a.grade === "A" || a.grade === "B" ? "bg-green-500/15 text-green-400" :
                        a.grade === "C" ? "bg-amber-500/15 text-amber-400" : "bg-red-500/15 text-red-400"
                      )}>{a.grade}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-[11px]">
                    {al && (
                      <div className="flex gap-0.5">
                        {[al.screen1, al.screen2, al.screen3].map((s, j) => (
                          <span key={j} className={cn("w-1.5 h-1.5 rounded-full", s ? "bg-green-500" : "bg-surface-2")} />
                        ))}
                      </div>
                    )}
                    <span className={cn("font-mono", isUp ? "text-green-400" : "text-red-400")}>
                      {a.ltp ? `₹${a.ltp.toLocaleString("en-IN")}` : "—"}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-2 border-t border-border text-[9px] text-muted flex gap-4">
          <span>↑↓ Navigate</span>
          <span>Enter Select</span>
          <span>Esc Close</span>
        </div>
      </div>
    </div>
  );
}
