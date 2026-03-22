"use client";

import { useEffect, useRef, useState } from "react";
import { useTradingStore } from "@/store/useTradingStore";
import type { WsState } from "@/store/useTradingStore";
import { cn } from "@/lib/utils";
import { RefreshCw } from "lucide-react";

const FRESHNESS_DOT: Record<string, string> = {
  live: "bg-green-500",
  stale: "bg-yellow-500",
  demo: "bg-amber-500",
  disconnected: "bg-red-500",
  reconnecting: "bg-yellow-500",
};

const FRESHNESS_LABEL: Record<string, string> = {
  live: "LIVE",
  stale: "STALE",
  demo: "DEMO",
  disconnected: "OFFLINE",
  reconnecting: "RECONNECTING",
};

const WS_STATE_LABEL: Record<WsState, string> = {
  connecting: "Connecting...",
  connected: "ON",
  reconnecting: "Reconnecting...",
  disconnected: "OFF",
  polling: "Polling",
};

const WS_STATE_COLOR: Record<WsState, string> = {
  connecting: "text-yellow-500/70",
  connected: "text-green-500/70",
  reconnecting: "text-yellow-500/70",
  disconnected: "text-red-500/70",
  polling: "text-amber-500/70",
};

const BROKER_STATUS_CONFIG: Record<string, { color: string; label: string; dot: string }> = {
  CONNECTED: { color: "text-green-500/70", label: "Broker: ON", dot: "bg-green-500" },
  CONNECTING: { color: "text-yellow-500/70", label: "Broker: Connecting...", dot: "bg-yellow-500 animate-pulse" },
  RECONNECTING: { color: "text-yellow-500/70", label: "Broker: Retrying...", dot: "bg-yellow-500 animate-pulse" },
  OFFLINE: { color: "text-red-500/70", label: "Broker: OFFLINE", dot: "bg-red-500" },
  UNKNOWN: { color: "text-muted", label: "Broker: --", dot: "bg-gray-500" },
};

function BrokerStatus() {
  const [status, setStatus] = useState("UNKNOWN");
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState(false);
  const brokerConnected = useTradingStore((s) => s.brokerConnected);

  // Poll broker status from heartbeat store updates
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const token = localStorage.getItem("elder_token");
        const res = await fetch("http://localhost:8000/api/broker/status", {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (res.ok) {
          const data = await res.json();
          setStatus(data.status || "UNKNOWN");
          setError(data.last_error || "");
        }
      } catch {
        // API not reachable
      }
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleRetry = async () => {
    setRetrying(true);
    try {
      const token = localStorage.getItem("elder_token");
      await fetch("http://localhost:8000/api/broker/retry", {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      setStatus("CONNECTING");
    } catch {
      // ignore
    }
    setTimeout(() => setRetrying(false), 5000);
  };

  const cfg = BROKER_STATUS_CONFIG[status] || BROKER_STATUS_CONFIG.UNKNOWN;

  return (
    <div className="flex items-center gap-1.5">
      <span className={cn("w-1.5 h-1.5 rounded-full", cfg.dot)} />
      <span className={cn("font-medium", cfg.color)} title={error || undefined}>
        {cfg.label}
      </span>
      {(status === "OFFLINE" || status === "UNKNOWN") && (
        <button
          onClick={handleRetry}
          disabled={retrying}
          className={cn(
            "px-1.5 py-0.5 rounded text-[9px] font-medium transition-colors",
            "bg-amber-500/20 text-amber-400 hover:bg-amber-500/30",
            retrying && "opacity-50 cursor-not-allowed",
          )}
          title={error ? `Error: ${error}` : "Retry broker connection"}
        >
          {retrying ? "Retrying..." : "Retry"}
        </button>
      )}
    </div>
  );
}

export function PipelineStatusBar() {
  const dataFreshness = useTradingStore((s) => s.dataFreshness);
  const tradingMode = useTradingStore((s) => s.tradingMode);
  const lastCandleTime = useTradingStore((s) => s.lastCandleTime);
  const brokerConnected = useTradingStore((s) => s.brokerConnected);
  const wsState = useTradingStore((s) => s.wsState);
  const tickCount = useTradingStore((s) => s.tickCount);
  const lastTickTime = useTradingStore((s) => s.lastTickTime);
  const fetchCandles = useTradingStore((s) => s.fetchCandles);
  const fetchIndicators = useTradingStore((s) => s.fetchIndicators);

  // Pulsing dot animation on tick
  const [pulsing, setPulsing] = useState(false);
  const prevTickCount = useRef(tickCount);

  useEffect(() => {
    if (tickCount !== prevTickCount.current) {
      prevTickCount.current = tickCount;
      setPulsing(true);
      const t = setTimeout(() => setPulsing(false), 300);
      return () => clearTimeout(t);
    }
  }, [tickCount]);

  // Tick rate (ticks per second) — rolling window
  const tickTimesRef = useRef<number[]>([]);
  const [tickRate, setTickRate] = useState(0);

  useEffect(() => {
    if (lastTickTime > 0) {
      const now = lastTickTime;
      tickTimesRef.current.push(now);
      // Keep only last 10 seconds
      const cutoff = now - 10_000;
      tickTimesRef.current = tickTimesRef.current.filter((t) => t > cutoff);
      const elapsed = (now - tickTimesRef.current[0]) / 1000;
      const rate = elapsed > 0 ? (tickTimesRef.current.length - 1) / elapsed : 0;
      setTickRate(Math.round(rate * 10) / 10);
    }
  }, [lastTickTime]);

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
      {/* Connection dot + data source — pulsing on tick */}
      <div className="flex items-center gap-1.5">
        <span
          className={cn(
            "w-1.5 h-1.5 rounded-full transition-transform duration-200",
            dotColor,
            pulsing && dataFreshness === "live" && "scale-[2] ring-1 ring-green-500/30",
          )}
        />
        <span
          className={cn(
            "font-semibold tracking-wide",
            dataFreshness === "live"
              ? "text-green-500"
              : dataFreshness === "demo"
              ? "text-amber-500"
              : dataFreshness === "stale" || dataFreshness === "reconnecting"
              ? "text-yellow-500"
              : "text-red-500"
          )}
        >
          {label}
        </span>
      </div>

      {/* Tick rate */}
      {dataFreshness === "live" && tickRate > 0 && (
        <span className="text-green-500/60 font-mono">
          {tickRate} tps
        </span>
      )}

      {/* Broker connection status with retry button */}
      <BrokerStatus />

      {/* Pipeline WS state */}
      <span className={cn("text-muted", WS_STATE_COLOR[wsState])}>
        WS: {WS_STATE_LABEL[wsState]}
      </span>

      {/* Last candle time */}
      {ageStr && (
        <span className="text-muted">
          Last bar: {ageStr}
        </span>
      )}

      {/* Polling banner */}
      {wsState === "polling" && (
        <span className="text-amber-500/80 text-[9px]">
          Live updates paused — refreshing every 5s
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
