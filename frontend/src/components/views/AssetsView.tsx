"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchCommandCenter, startPipeline, stopPipeline } from "@/lib/api";
import type { CommandCenterAsset } from "@/lib/api";
import { useTradingStore } from "@/store/useTradingStore";
import { cn } from "@/lib/utils";
import { Loader2, Play, Square, PlayCircle, StopCircle } from "lucide-react";

// ── Available instruments (mirrors backend TRACKED_INSTRUMENTS) ──
const AVAILABLE_INSTRUMENTS = [
  { symbol: "NIFTY", exchange: "NFO", group: "NFO \u2014 Index Futures" },
  { symbol: "BANKNIFTY", exchange: "NFO", group: "NFO \u2014 Index Futures" },
  { symbol: "GOLDM", exchange: "MCX", group: "MCX \u2014 Metals" },
  { symbol: "SILVERM", exchange: "MCX", group: "MCX \u2014 Metals" },
  { symbol: "COPPER", exchange: "MCX", group: "MCX \u2014 Metals" },
  { symbol: "ALUMINIUM", exchange: "MCX", group: "MCX \u2014 Metals" },
  { symbol: "ZINC", exchange: "MCX", group: "MCX \u2014 Metals" },
  { symbol: "NATGASMINI", exchange: "MCX", group: "MCX \u2014 Energy" },
  { symbol: "CRUDEOILM", exchange: "MCX", group: "MCX \u2014 Energy" },
];

// Group instruments by group field
function groupBy<T>(arr: T[], key: (item: T) => string): Record<string, T[]> {
  const result: Record<string, T[]> = {};
  for (const item of arr) {
    const k = key(item);
    if (!result[k]) result[k] = [];
    result[k].push(item);
  }
  return result;
}

const GROUPS = groupBy(AVAILABLE_INSTRUMENTS, (i) => i.group);
const GROUP_ORDER = Object.keys(GROUPS);

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export default function AssetsView() {
  const [activeAssets, setActiveAssets] = useState<CommandCenterAsset[]>([]);
  const [loadingSymbols, setLoadingSymbols] = useState<Set<string>>(new Set());
  const [bulkAction, setBulkAction] = useState<"starting" | "stopping" | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const setCommandCenterAssets = useTradingStore((s) => s.setCommandCenterAssets);

  const refresh = useCallback(async () => {
    try {
      const res = await fetchCommandCenter();
      const assets = res.assets || [];
      setActiveAssets(assets);
      setCommandCenterAssets(assets);
    } catch {
      // Keep existing data on failure
    }
  }, [setCommandCenterAssets]);

  useEffect(() => {
    refresh().finally(() => setInitialLoading(false));
    const interval = setInterval(refresh, 10_000);
    return () => clearInterval(interval);
  }, [refresh]);

  const activeKeys = new Set(activeAssets.map((a) => `${a.symbol}:${a.exchange}`));

  const isActive = (symbol: string, exchange: string) =>
    activeKeys.has(`${symbol}:${exchange}`);

  const isLoading = (symbol: string) => loadingSymbols.has(symbol);

  const getAssetData = (symbol: string, exchange: string) =>
    activeAssets.find((a) => a.symbol === symbol && a.exchange === exchange);

  const handleToggle = async (symbol: string, exchange: string) => {
    if (isLoading(symbol)) return;

    setLoadingSymbols((prev) => new Set(prev).add(symbol));
    try {
      if (isActive(symbol, exchange)) {
        await stopPipeline(symbol, exchange);
      } else {
        await startPipeline(symbol, exchange);
      }
      await refresh();
    } catch {
      // Toggle failed
    } finally {
      setLoadingSymbols((prev) => {
        const next = new Set(prev);
        next.delete(symbol);
        return next;
      });
    }
  };

  const handleStartAll = async () => {
    setBulkAction("starting");
    const inactive = AVAILABLE_INSTRUMENTS.filter(
      (i) => !isActive(i.symbol, i.exchange)
    );
    for (const inst of inactive) {
      setLoadingSymbols((prev) => new Set(prev).add(inst.symbol));
      try {
        await startPipeline(inst.symbol, inst.exchange);
      } catch {
        // Skip failed starts
      }
      setLoadingSymbols((prev) => {
        const next = new Set(prev);
        next.delete(inst.symbol);
        return next;
      });
      if (inst !== inactive[inactive.length - 1]) {
        await delay(1000);
      }
    }
    await refresh();
    setBulkAction(null);
  };

  const handleStopAll = async () => {
    setBulkAction("stopping");
    const active = AVAILABLE_INSTRUMENTS.filter((i) =>
      isActive(i.symbol, i.exchange)
    );
    for (const inst of active) {
      setLoadingSymbols((prev) => new Set(prev).add(inst.symbol));
      try {
        await stopPipeline(inst.symbol, inst.exchange);
      } catch {
        // Skip failed stops
      }
      setLoadingSymbols((prev) => {
        const next = new Set(prev);
        next.delete(inst.symbol);
        return next;
      });
    }
    await refresh();
    setBulkAction(null);
  };

  const activeCount = AVAILABLE_INSTRUMENTS.filter((i) =>
    isActive(i.symbol, i.exchange)
  ).length;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-6 h-11 border-b border-border shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-[13px] font-semibold text-foreground tracking-tight">
            Tracked Instruments
          </h1>
          <span className="text-[11px] text-muted">
            {activeCount} / {AVAILABLE_INSTRUMENTS.length} active
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleStartAll}
            disabled={bulkAction !== null || activeCount === AVAILABLE_INSTRUMENTS.length}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-medium transition-colors",
              "bg-green-500/10 text-green-400 hover:bg-green-500/20 border border-green-500/20",
              "disabled:opacity-40 disabled:cursor-not-allowed"
            )}
          >
            <PlayCircle className="w-3.5 h-3.5" />
            {bulkAction === "starting" ? "Starting..." : "Start All"}
          </button>
          <button
            onClick={handleStopAll}
            disabled={bulkAction !== null || activeCount === 0}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-medium transition-colors",
              "bg-red-500/10 text-red-400 hover:bg-red-500/20 border border-red-500/20",
              "disabled:opacity-40 disabled:cursor-not-allowed"
            )}
          >
            <StopCircle className="w-3.5 h-3.5" />
            {bulkAction === "stopping" ? "Stopping..." : "Stop All"}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-5">
        <div className="max-w-3xl mx-auto space-y-5">
          {initialLoading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-muted text-sm">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading instruments...
            </div>
          ) : (
            GROUP_ORDER.map((group) => (
              <div key={group}>
                {/* Group header */}
                <h2 className="text-[11px] font-semibold text-muted uppercase tracking-wider mb-2 px-1">
                  {group}
                </h2>
                {/* Group card */}
                <div className="rounded-lg bg-surface border border-border overflow-hidden divide-y divide-border/50">
                  {GROUPS[group].map((inst) => {
                    const active = isActive(inst.symbol, inst.exchange);
                    const loading = isLoading(inst.symbol);
                    const data = getAssetData(inst.symbol, inst.exchange);
                    const mode = data?.trading_mode ?? null;

                    return (
                      <div
                        key={inst.symbol}
                        className={cn(
                          "flex items-center justify-between px-4 py-3 transition-colors",
                          active ? "bg-green-500/[0.03]" : ""
                        )}
                      >
                        {/* Left: symbol + status */}
                        <div className="flex items-center gap-3 min-w-0">
                          {/* Status dot */}
                          <span
                            className={cn(
                              "w-2 h-2 rounded-full shrink-0",
                              active
                                ? "bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.4)]"
                                : "bg-surface-2 border border-border"
                            )}
                          />
                          {/* Symbol */}
                          <span className="text-[13px] font-semibold text-foreground">
                            {inst.symbol}
                          </span>
                          {/* Exchange tag */}
                          <span className="text-[9px] text-muted px-1.5 py-0.5 rounded bg-surface-2 font-medium">
                            {inst.exchange}
                          </span>
                          {/* Status text */}
                          <span
                            className={cn(
                              "text-[10px] font-medium",
                              active ? "text-green-400" : "text-muted"
                            )}
                          >
                            {active ? "Active" : "Inactive"}
                          </span>
                        </div>

                        {/* Right: mode badge + toggle */}
                        <div className="flex items-center gap-3">
                          {/* Mode badge */}
                          {active && mode ? (
                            <span
                              className={cn(
                                "px-1.5 py-0.5 rounded-full text-[9px] font-bold",
                                mode === "LIVE"
                                  ? "bg-red-500/80 text-white"
                                  : "bg-amber-500/20 text-amber-400"
                              )}
                            >
                              {mode}
                            </span>
                          ) : (
                            <span className="text-[10px] text-muted w-10 text-center">
                              --
                            </span>
                          )}

                          {/* Toggle button */}
                          <button
                            onClick={() => handleToggle(inst.symbol, inst.exchange)}
                            disabled={loading || bulkAction !== null}
                            className={cn(
                              "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-medium transition-all min-w-[72px] justify-center",
                              "disabled:cursor-not-allowed",
                              loading && "opacity-60",
                              active
                                ? "bg-red-500/10 text-red-400 hover:bg-red-500/20 border border-red-500/20"
                                : "bg-green-500/10 text-green-400 hover:bg-green-500/20 border border-green-500/20"
                            )}
                          >
                            {loading ? (
                              <Loader2 className="w-3 h-3 animate-spin" />
                            ) : active ? (
                              <>
                                <Square className="w-3 h-3" />
                                Stop
                              </>
                            ) : (
                              <>
                                <Play className="w-3 h-3" />
                                Start
                              </>
                            )}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
