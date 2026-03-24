"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchCommandCenter, startPipeline, stopPipeline } from "@/lib/api";
import type { CommandCenterAsset } from "@/lib/api";
import { useTradingStore } from "@/store/useTradingStore";
import { cn } from "@/lib/utils";
import {
  Loader2,
  Play,
  Square,
  PlayCircle,
  StopCircle,
  ChevronDown,
  ChevronRight,
  Save,
  RotateCw,
} from "lucide-react";

// ── Available instruments (mirrors backend TRACKED_INSTRUMENTS) ──
const AVAILABLE_INSTRUMENTS = [
  { symbol: "NIFTY", exchange: "NFO", group: "NFO — Index Futures", assetClass: "INDEX_FO" },
  { symbol: "BANKNIFTY", exchange: "NFO", group: "NFO — Index Futures", assetClass: "INDEX_FO" },
  { symbol: "GOLDM", exchange: "MCX", group: "MCX — Metals", assetClass: "COMMODITY" },
  { symbol: "SILVERM", exchange: "MCX", group: "MCX — Metals", assetClass: "COMMODITY" },
  { symbol: "COPPER", exchange: "MCX", group: "MCX — Metals", assetClass: "COMMODITY" },
  { symbol: "ALUMINIUM", exchange: "MCX", group: "MCX — Metals", assetClass: "COMMODITY" },
  { symbol: "ZINC", exchange: "MCX", group: "MCX — Metals", assetClass: "COMMODITY" },
  { symbol: "NATGASMINI", exchange: "MCX", group: "MCX — Energy", assetClass: "COMMODITY" },
  { symbol: "CRUDEOILM", exchange: "MCX", group: "MCX — Energy", assetClass: "COMMODITY" },
];

const DEFAULT_TIMEFRAMES: Record<string, { s1: string; s2: string; s3: string }> = {
  INDEX_FO: { s1: "1d", s2: "1h", s3: "15m" },
  COMMODITY: { s1: "1d", s2: "1h", s3: "15m" },
  EQUITY: { s1: "1w", s2: "1d", s3: "1h" },
};

const TIMEFRAME_OPTIONS = ["Default", "1w", "1d", "4h", "1h", "30m", "15m", "5m"];

// ── Helpers ──
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

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetchRaw(path: string, init?: RequestInit) {
  const authHeaders: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("elder_token");
    if (token) authHeaders["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${BASE}${path}`, { ...init, headers: authHeaders });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `API ${res.status}`);
  }
  return res.json();
}

// ── Per-asset settings type ──
interface AssetSettings {
  symbol: string;
  exchange: string;
  trading_mode: "PAPER" | "LIVE";
  screen1_timeframe: string | null;
  screen2_timeframe: string | null;
  screen3_timeframe: string | null;
  max_risk_pct_override: number | null;
  default_position_type: "INTRADAY" | "POSITIONAL" | null;
}

// ── Inline config panel for expanded asset row ──
function AssetConfigPanel({
  inst,
  currentSettings,
  active,
  onSaved,
}: {
  inst: (typeof AVAILABLE_INSTRUMENTS)[number];
  currentSettings: AssetSettings | null;
  active: boolean;
  onSaved: (notice: string | null) => void;
}) {
  const defaults = DEFAULT_TIMEFRAMES[inst.assetClass] || DEFAULT_TIMEFRAMES.EQUITY;

  const [mode, setMode] = useState<"PAPER" | "LIVE">(
    currentSettings?.trading_mode ?? "PAPER"
  );
  const [s1, setS1] = useState(currentSettings?.screen1_timeframe ?? "");
  const [s2, setS2] = useState(currentSettings?.screen2_timeframe ?? "");
  const [s3, setS3] = useState(currentSettings?.screen3_timeframe ?? "");
  const [riskPct, setRiskPct] = useState(
    currentSettings?.max_risk_pct_override != null
      ? String(currentSettings.max_risk_pct_override)
      : ""
  );
  const [positionType, setPositionType] = useState<"POSITIONAL" | "INTRADAY">(
    currentSettings?.default_position_type ?? "POSITIONAL"
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await apiFetchRaw(
        `/api/strategy/pipeline/asset-settings/${encodeURIComponent(inst.symbol)}`,
        {
          method: "PUT",
          body: JSON.stringify({
            exchange: inst.exchange,
            trading_mode: mode,
            screen1_timeframe: s1 || null,
            screen2_timeframe: s2 || null,
            screen3_timeframe: s3 || null,
            max_risk_pct_override: riskPct ? parseFloat(riskPct) : null,
            default_position_type: positionType,
            user_id: 1,
          }),
        }
      );
      if (res?.restarted) {
        onSaved("Pipeline restarted with new timeframes");
      } else {
        onSaved(null);
      }
    } catch (err: any) {
      setError(err.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="px-4 pb-4 pt-1">
      <div className="rounded-md bg-surface-2 border border-border p-4 space-y-4">
        {/* Trading Mode */}
        <div>
          <label className="text-[11px] font-semibold text-muted uppercase tracking-wider block mb-2">
            Trading Mode
          </label>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setMode("PAPER")}
              className={cn(
                "px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors",
                mode === "PAPER"
                  ? "bg-amber-500/20 text-amber-400 border-amber-500/40"
                  : "bg-background text-muted border-border hover:border-muted"
              )}
            >
              PAPER
            </button>
            <button
              onClick={() => setMode("LIVE")}
              className={cn(
                "px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors",
                mode === "LIVE"
                  ? "bg-red-500/20 text-red-400 border-red-500/40"
                  : "bg-background text-muted border-border hover:border-muted"
              )}
            >
              LIVE
            </button>
          </div>
        </div>

        {/* Position Type */}
        <div>
          <label className="text-[11px] font-semibold text-muted uppercase tracking-wider block mb-2">
            Position Type
          </label>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPositionType("POSITIONAL")}
              className={cn(
                "px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors",
                positionType === "POSITIONAL"
                  ? "bg-blue-500/20 text-blue-400 border-blue-500/40"
                  : "bg-background text-muted border-border hover:border-muted"
              )}
            >
              POSITIONAL
            </button>
            <button
              onClick={() => setPositionType("INTRADAY")}
              className={cn(
                "px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors",
                positionType === "INTRADAY"
                  ? "bg-purple-500/20 text-purple-400 border-purple-500/40"
                  : "bg-background text-muted border-border hover:border-muted"
              )}
            >
              INTRADAY
            </button>
          </div>
          <span className="text-[10px] text-muted/60 mt-1 block">
            {positionType === "POSITIONAL"
              ? "Carries overnight with reduced risk sizing"
              : "Auto-closes at EOD cutoff"}
          </span>
        </div>

        {/* Timeframes */}
        <div>
          <label className="text-[11px] font-semibold text-muted uppercase tracking-wider block mb-2">
            Timeframes (Triple Screen)
          </label>
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: "Screen 1 (Tide)", value: s1, setter: setS1, def: defaults.s1 },
              { label: "Screen 2 (Wave)", value: s2, setter: setS2, def: defaults.s2 },
              { label: "Screen 3 (Entry)", value: s3, setter: setS3, def: defaults.s3 },
            ].map((screen) => (
              <div key={screen.label}>
                <span className="text-[10px] text-muted block mb-1">{screen.label}</span>
                <select
                  value={screen.value}
                  onChange={(e) => screen.setter(e.target.value)}
                  className="w-full bg-background border border-border rounded px-2 py-1.5 text-[11px] text-foreground focus:outline-none focus:border-muted"
                >
                  {TIMEFRAME_OPTIONS.map((tf) => (
                    <option key={tf} value={tf === "Default" ? "" : tf}>
                      {tf === "Default" ? `Default (${screen.def})` : tf}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
        </div>

        {/* Risk Override */}
        <div>
          <label className="text-[11px] font-semibold text-muted uppercase tracking-wider block mb-2">
            Risk Override
          </label>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-muted">Max risk/trade:</span>
            <input
              type="number"
              step="0.1"
              min="0.1"
              max="10"
              value={riskPct}
              onChange={(e) => setRiskPct(e.target.value)}
              placeholder="2.0"
              className="w-20 bg-background border border-border rounded px-2 py-1.5 text-[11px] text-foreground focus:outline-none focus:border-muted placeholder:text-muted/50"
            />
            <span className="text-[11px] text-muted">%</span>
            <span className="text-[10px] text-muted/60 ml-1">(blank = use default 2%)</span>
          </div>
        </div>

        {/* Save */}
        <div className="flex items-center gap-3 pt-1">
          <button
            onClick={handleSave}
            disabled={saving}
            className={cn(
              "flex items-center gap-1.5 px-4 py-1.5 rounded-md text-[11px] font-medium transition-colors",
              "bg-blue-500/15 text-blue-400 hover:bg-blue-500/25 border border-blue-500/30",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            {saving ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Save className="w-3 h-3" />
            )}
            Save Changes
          </button>
          {error && (
            <span className="text-[10px] text-red-400">{error}</span>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main component ──
export default function AssetsView() {
  const [activeAssets, setActiveAssets] = useState<CommandCenterAsset[]>([]);
  const [loadingSymbols, setLoadingSymbols] = useState<Set<string>>(new Set());
  const [bulkAction, setBulkAction] = useState<"starting" | "stopping" | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);
  const [assetSettings, setAssetSettings] = useState<Record<string, AssetSettings>>({});
  const [notice, setNotice] = useState<string | null>(null);
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

  const fetchSettings = useCallback(async () => {
    try {
      const res = await apiFetchRaw("/api/strategy/pipeline/asset-settings");
      if (res && typeof res === "object") {
        const map: Record<string, AssetSettings> = {};
        const items = Array.isArray(res) ? res : res.settings || [];
        for (const s of items) {
          if (s.symbol) map[`${s.symbol}:${s.exchange}`] = s;
        }
        setAssetSettings(map);
      }
    } catch {
      // Settings endpoint may not exist yet — silently ignore
    }
  }, []);

  useEffect(() => {
    Promise.all([refresh(), fetchSettings()]).finally(() => setInitialLoading(false));
    const interval = setInterval(refresh, 10_000);
    return () => clearInterval(interval);
  }, [refresh, fetchSettings]);

  // Auto-dismiss notice
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(t);
  }, [notice]);

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

  const getDisplayTimeframes = (inst: (typeof AVAILABLE_INSTRUMENTS)[number]) => {
    const key = `${inst.symbol}:${inst.exchange}`;
    const settings = assetSettings[key];
    const defaults = DEFAULT_TIMEFRAMES[inst.assetClass] || DEFAULT_TIMEFRAMES.EQUITY;
    const s1 = settings?.screen1_timeframe || defaults.s1;
    const s2 = settings?.screen2_timeframe || defaults.s2;
    const s3 = settings?.screen3_timeframe || defaults.s3;
    return `${s1}/${s2}/${s3}`;
  };

  const handleSaved = async (msg: string | null) => {
    if (msg) setNotice(msg);
    await Promise.all([refresh(), fetchSettings()]);
  };

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

      {/* Notice toast */}
      {notice && (
        <div className="mx-6 mt-3 px-3 py-2 rounded-md bg-blue-500/10 border border-blue-500/20 text-blue-400 text-[11px] font-medium flex items-center gap-2">
          <RotateCw className="w-3 h-3" />
          {notice}
        </div>
      )}

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
                    const modeFromData = data?.trading_mode ?? null;
                    const key = `${inst.symbol}:${inst.exchange}`;
                    const settings = assetSettings[key] || null;
                    const isExpanded = expandedSymbol === key;
                    const displayMode =
                      settings?.trading_mode ?? modeFromData ?? null;

                    return (
                      <div
                        key={inst.symbol}
                        className={cn(
                          "transition-colors",
                          active ? "bg-green-500/[0.03]" : ""
                        )}
                      >
                        {/* Collapsed row */}
                        <div className="flex items-center justify-between px-4 py-3">
                          {/* Left: symbol + status + timeframes */}
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
                            {/* Mode badge */}
                            {displayMode ? (
                              <span
                                className={cn(
                                  "px-1.5 py-0.5 rounded-full text-[9px] font-bold",
                                  displayMode === "LIVE"
                                    ? "bg-red-500/80 text-white"
                                    : "bg-amber-500/20 text-amber-400"
                                )}
                              >
                                {displayMode}
                              </span>
                            ) : (
                              <span className="text-[10px] text-muted w-10 text-center">
                                --
                              </span>
                            )}
                            {/* Position Type badge */}
                            {settings?.default_position_type && (
                              <span
                                className={cn(
                                  "px-1.5 py-0.5 rounded-full text-[9px] font-bold",
                                  settings.default_position_type === "INTRADAY"
                                    ? "bg-purple-500/20 text-purple-400"
                                    : "bg-blue-500/20 text-blue-400"
                                )}
                              >
                                {settings.default_position_type === "INTRADAY" ? "INTRA" : "POS"}
                              </span>
                            )}
                            {/* Timeframes */}
                            <span className="text-[10px] text-muted font-mono">
                              Screen: {getDisplayTimeframes(inst)}
                            </span>
                          </div>

                          {/* Right: toggle + expand chevron */}
                          <div className="flex items-center gap-2">
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
                            {/* Expand chevron */}
                            <button
                              onClick={() =>
                                setExpandedSymbol(isExpanded ? null : key)
                              }
                              className="p-1.5 rounded hover:bg-surface-2 transition-colors text-muted hover:text-foreground"
                            >
                              {isExpanded ? (
                                <ChevronDown className="w-3.5 h-3.5" />
                              ) : (
                                <ChevronRight className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </div>
                        </div>

                        {/* Expanded config panel */}
                        {isExpanded && (
                          <AssetConfigPanel
                            inst={inst}
                            currentSettings={settings}
                            active={active}
                            onSaved={handleSaved}
                          />
                        )}
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
