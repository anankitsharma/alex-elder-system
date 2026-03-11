"use client";

import { useTradingStore } from "@/store/useTradingStore";
import { cn } from "@/lib/utils";
import { RefreshCw } from "lucide-react";

const FRESHNESS_DOT: Record<string, string> = {
  live: "bg-green-500",
  stale: "bg-yellow-500",
  demo: "bg-amber-500",
  disconnected: "bg-red-500",
};

const FRESHNESS_LABEL: Record<string, string> = {
  live: "LIVE",
  stale: "STALE",
  demo: "DEMO",
  disconnected: "OFFLINE",
};

export function PipelineStatusBar() {
  const dataFreshness = useTradingStore((s) => s.dataFreshness);
  const tradingMode = useTradingStore((s) => s.tradingMode);
  const lastCandleTime = useTradingStore((s) => s.lastCandleTime);
  const brokerConnected = useTradingStore((s) => s.brokerConnected);
  const pipelineWsConnected = useTradingStore((s) => s.pipelineWsConnected);
  const fetchCandles = useTradingStore((s) => s.fetchCandles);
  const fetchIndicators = useTradingStore((s) => s.fetchIndicators);

  const dotColor = FRESHNESS_DOT[dataFreshness] || FRESHNESS_DOT.disconnected;
  const label = FRESHNESS_LABEL[dataFreshness] || "OFFLINE";

  // Calculate candle age
  let ageStr = "";
  if (lastCandleTime) {
    const age = Date.now() - new Date(lastCandleTime).getTime();
    if (age < 60_000) ageStr = "< 1m ago";
    else if (age < 3600_000) ageStr = `${Math.floor(age / 60_000)}m ago`;
    else if (age < 86400_000) ageStr = `${Math.floor(age / 3600_000)}h ago`;
    else ageStr = `${Math.floor(age / 86400_000)}d ago`;
  }

  const handleRefresh = () => {
    fetchCandles();
    fetchIndicators();
  };

  return (
    <div className="flex items-center gap-3 px-4 h-7 border-b border-border bg-surface text-[10px] shrink-0">
      {/* Connection dot + data source */}
      <div className="flex items-center gap-1.5">
        <span className={cn("w-1.5 h-1.5 rounded-full", dotColor)} />
        <span
          className={cn(
            "font-semibold tracking-wide",
            dataFreshness === "live"
              ? "text-green-500"
              : dataFreshness === "demo"
              ? "text-amber-500"
              : dataFreshness === "stale"
              ? "text-yellow-500"
              : "text-red-500"
          )}
        >
          {label}
        </span>
      </div>

      {/* Broker feed status */}
      <span className={cn("text-muted", brokerConnected ? "text-green-500/70" : "text-red-500/70")}>
        Feed: {brokerConnected ? "ON" : "OFF"}
      </span>

      {/* Pipeline WS */}
      <span className={cn("text-muted", pipelineWsConnected ? "text-green-500/70" : "text-red-500/70")}>
        WS: {pipelineWsConnected ? "ON" : "OFF"}
      </span>

      {/* Last candle time */}
      {ageStr && (
        <span className="text-muted">
          Last bar: {ageStr}
        </span>
      )}

      <div className="flex-1" />

      {/* Trading mode badge */}
      <span
        className={cn(
          "px-1.5 py-0.5 rounded font-semibold tracking-wide",
          tradingMode === "LIVE"
            ? "bg-green-500/10 text-green-500 border border-green-500/20"
            : "bg-amber-500/10 text-amber-500 border border-amber-500/20"
        )}
      >
        {tradingMode}
        {tradingMode === "LIVE" && (
          <span className="ml-1 text-[9px] opacity-70">Real money</span>
        )}
      </span>

      {/* Refresh button */}
      <button
        onClick={handleRefresh}
        className="p-0.5 rounded text-muted hover:text-foreground hover:bg-surface-2 transition-colors"
        title="Refresh data"
      >
        <RefreshCw className="w-3 h-3" />
      </button>
    </div>
  );
}
