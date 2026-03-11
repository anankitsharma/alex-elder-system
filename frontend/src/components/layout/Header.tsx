"use client";

import { useEffect, useState } from "react";
import { Activity, Wifi, WifiOff, BarChart3 } from "lucide-react";
import { fetchHealth, type HealthResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

interface HeaderProps {
  wsConnected: boolean;
}

export function Header({ wsConnected }: HeaderProps) {
  const [health, setHealth] = useState<HealthResponse | null>(null);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch(() => setHealth(null));

    const id = setInterval(() => {
      fetchHealth()
        .then(setHealth)
        .catch(() => setHealth(null));
    }, 30000);
    return () => clearInterval(id);
  }, []);

  const mode = health?.trading_mode || "—";
  const isPaper = mode === "PAPER";
  const apiUp = health !== null;

  return (
    <header className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface">
      <div className="flex items-center gap-3">
        <BarChart3 className="w-5 h-5 text-accent" />
        <h1 className="text-sm font-semibold tracking-wide">
          Elder Trading System
        </h1>
      </div>

      <div className="flex items-center gap-4 text-xs">
        {/* Trading mode badge */}
        <span
          className={cn(
            "px-2 py-0.5 rounded font-medium",
            isPaper
              ? "bg-amber/15 text-amber"
              : "bg-green/15 text-green"
          )}
        >
          {mode}
        </span>

        {/* API status */}
        <span className="flex items-center gap-1.5">
          <span
            className={cn(
              "w-1.5 h-1.5 rounded-full",
              apiUp ? "bg-green animate-pulse-dot" : "bg-red"
            )}
          />
          <span className="text-muted">API</span>
        </span>

        {/* WS status */}
        <span className="flex items-center gap-1.5">
          {wsConnected ? (
            <Wifi className="w-3.5 h-3.5 text-green" />
          ) : (
            <WifiOff className="w-3.5 h-3.5 text-red" />
          )}
          <span className="text-muted">Feed</span>
        </span>

        {/* Risk info */}
        {health && (
          <span className="text-muted">
            Risk: {health.risk_per_trade} / {health.portfolio_risk_limit}
          </span>
        )}
      </div>
    </header>
  );
}
