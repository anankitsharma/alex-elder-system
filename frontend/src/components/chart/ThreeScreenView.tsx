"use client";

import { useState, useEffect, useCallback } from "react";
import TradingViewChart from "./TradingViewChart";
import SignalPanel from "@/components/panels/SignalPanel";
import { useScreenData } from "@/hooks/useScreenData";
import { fetchScreenConfig, type ScreenConfig } from "@/lib/api";
import { Loader2, Maximize2, Minimize2 } from "lucide-react";
import { useTradingStore } from "@/store/useTradingStore";

interface ThreeScreenViewProps {
  symbol: string;
  exchange: string;
}

const TF_LABELS: Record<string, string> = {
  "1w": "Weekly", "1d": "Daily", "4h": "4H", "1h": "Hourly",
  "15m": "15min", "5m": "5min", "1m": "1min",
};

const TF_DAYS: Record<string, number> = {
  "1w": 730, "1d": 365, "4h": 180, "1h": 90,
  "15m": 30, "5m": 14, "1m": 7,
};

interface ScreenDef {
  label: string;
  interval: string;
  days: number;
  screen: number;
}

// ── Screen header ─────────────────────────────────────────────

function ScreenHeader({
  label, source, barCount, zoomed, onZoom,
}: {
  label: string;
  source: "live" | "demo" | null;
  barCount: number;
  zoomed: boolean;
  onZoom: () => void;
}) {
  return (
    <div className="flex items-center justify-between px-2 py-1 text-[11px]">
      <span className="font-medium text-foreground">{label}</span>
      <div className="flex items-center gap-2">
        {source === "demo" && barCount > 0 && (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-medium bg-amber/15 text-amber">
            DEMO
          </span>
        )}
        <span className="text-muted font-mono">
          {barCount > 0 && `${barCount} bars`}
        </span>
        <button
          onClick={onZoom}
          className="p-0.5 rounded hover:bg-border/50 text-muted hover:text-foreground transition-colors"
          title={zoomed ? "Exit zoom" : "Zoom in"}
        >
          {zoomed ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
        </button>
      </div>
    </div>
  );
}

// ── Unified Screen Panel using TradingViewChart ──────────────

function ScreenPanel({
  symbol, exchange, label, interval, days, screen, zoomed, onZoom,
  showMACD = false, showForceIndex = false, showElderRay = false,
}: {
  symbol: string; exchange: string; label: string;
  interval: string; days: number; screen: number;
  zoomed: boolean; onZoom: () => void;
  showMACD?: boolean; showForceIndex?: boolean; showElderRay?: boolean;
}) {
  const { candles, indicators, loading, error, source } = useScreenData(symbol, exchange, interval, days, screen);

  const placeholderH = zoomed ? 600 : 300;

  return (
    <div className="flex flex-col relative">
      <ScreenHeader label={label} source={source} barCount={candles.length} zoomed={zoomed} onZoom={onZoom} />
      {loading ? (
        <div className="flex items-center justify-center bg-surface border border-border rounded" style={{ height: placeholderH }}>
          <Loader2 className="w-5 h-5 text-muted animate-spin" />
        </div>
      ) : error ? (
        <div className="flex items-center justify-center bg-surface border border-border rounded text-xs text-red" style={{ height: placeholderH }}>
          {error}
        </div>
      ) : candles.length === 0 ? (
        <div className="flex items-center justify-center bg-surface border border-border rounded text-xs text-muted" style={{ height: placeholderH }}>
          No data
        </div>
      ) : (
        <div style={{ height: zoomed ? 700 : 350 }}>
          <TradingViewChart
            candles={candles}
            indicators={indicators}
            showVolume={zoomed}
            showMACD={showMACD}
            showForceIndex={showForceIndex}
            showElderRay={showElderRay}
          />
        </div>
      )}
    </div>
  );
}

// ── Screen config ─────────────────────────────────────────────

function getDefaultScreens(exchange: string): ScreenDef[] {
  if (exchange === "NFO" || exchange === "MCX") {
    return [
      { label: "Screen 1 — Daily (Tide)", interval: "1d", days: 365, screen: 1 },
      { label: "Screen 2 — Hourly (Wave)", interval: "1h", days: 90, screen: 2 },
      { label: "Screen 3 — 15min (Ripple)", interval: "15m", days: 30, screen: 3 },
    ];
  }
  return [
    { label: "Screen 1 — Weekly (Tide)", interval: "1w", days: 730, screen: 1 },
    { label: "Screen 2 — Daily (Wave)", interval: "1d", days: 365, screen: 2 },
    { label: "Screen 3 — Intraday (Ripple)", interval: "15m", days: 30, screen: 3 },
  ];
}

function useScreenConfig(symbol: string, exchange: string): ScreenDef[] {
  const [screens, setScreens] = useState<ScreenDef[]>(() => getDefaultScreens(exchange));

  useEffect(() => {
    setScreens(getDefaultScreens(exchange));
    fetchScreenConfig(symbol, exchange)
      .then((cfg: ScreenConfig) => {
        const s1tf = cfg.screens["1"]?.timeframe ?? "1w";
        const s2tf = cfg.screens["2"]?.timeframe ?? "1d";
        const s3tf = cfg.screens["3"]?.timeframe ?? "15m";
        setScreens([
          {
            label: `Screen 1 — ${TF_LABELS[s1tf] ?? s1tf} (Tide)`,
            interval: s1tf, days: TF_DAYS[s1tf] ?? 365, screen: 1,
          },
          {
            label: `Screen 2 — ${TF_LABELS[s2tf] ?? s2tf} (Wave)`,
            interval: s2tf, days: TF_DAYS[s2tf] ?? 365, screen: 2,
          },
          {
            label: `Screen 3 — ${TF_LABELS[s3tf] ?? s3tf} (Ripple)`,
            interval: s3tf, days: TF_DAYS[s3tf] ?? 30, screen: 3,
          },
        ]);
      })
      .catch(() => { /* keep defaults */ });
  }, [symbol, exchange]);

  return screens;
}

// ── Main Three Screen View ────────────────────────────────────

export function ThreeScreenView({ symbol, exchange }: ThreeScreenViewProps) {
  const screens = useScreenConfig(symbol, exchange);

  // Stagger screen loading
  const [showScreen, setShowScreen] = useState(1);
  useEffect(() => {
    setShowScreen(1);
    const t2 = setTimeout(() => setShowScreen(2), 2000);
    const t3 = setTimeout(() => setShowScreen(3), 4000);
    return () => { clearTimeout(t2); clearTimeout(t3); };
  }, [symbol, exchange]);

  // Zoom state
  const [zoomedScreen, setZoomedScreen] = useState<number | null>(null);

  const toggleZoom = useCallback((screen: number) => {
    setZoomedScreen((prev) => (prev === screen ? null : screen));
  }, []);

  // Screen 2 data for SignalPanel from store
  const s2tf = screens[1]?.interval ?? "1d";
  const s2Slice = useTradingStore((s) => s.screenData[s2tf]);
  const s2Candles = s2Slice?.candles ?? [];
  const s2Indicators = s2Slice?.indicators ?? null;

  // Sub-pane config per screen (Elder's methodology):
  // Screen 1 (Tide): Candle + MACD
  // Screen 2 (Wave): Candle + MACD + Force Index + Elder-Ray (full suite)
  // Screen 3 (Ripple): Candle + Force Index
  const renderScreen = (screenIdx: number, zoomed: boolean) => {
    const def = screens[screenIdx];
    const onZoom = () => toggleZoom(screenIdx + 1);

    const subPanes = screenIdx === 0
      ? { showMACD: true, showForceIndex: false, showElderRay: false }
      : screenIdx === 1
      ? { showMACD: true, showForceIndex: true, showElderRay: true }
      : { showMACD: false, showForceIndex: true, showElderRay: false };

    return (
      <ScreenPanel
        symbol={symbol} exchange={exchange}
        label={def.label} interval={def.interval} days={def.days} screen={def.screen}
        zoomed={zoomed} onZoom={onZoom}
        {...subPanes}
      />
    );
  };

  const loadingPlaceholder = (h: number) => (
    <div
      className="flex items-center justify-center bg-surface border border-border rounded"
      style={{ height: h }}
    >
      <Loader2 className="w-5 h-5 text-muted animate-spin" />
    </div>
  );

  return (
    <div className="flex flex-col gap-2 overflow-auto p-1">
      {zoomedScreen != null ? (
        <div className="flex flex-col gap-2">
          {renderScreen(zoomedScreen - 1, true)}
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-2">
          {renderScreen(0, false)}
          {showScreen >= 2 ? renderScreen(1, false) : loadingPlaceholder(350)}
          {showScreen >= 3 ? renderScreen(2, false) : loadingPlaceholder(350)}
        </div>
      )}
      <div className="border border-border rounded bg-surface">
        <SignalPanel
          symbol={symbol}
          exchange={exchange}
          candles={s2Candles}
          indicators={s2Indicators}
        />
      </div>
    </div>
  );
}
