"use client";

import { useState, useEffect, useCallback } from "react";
import { CandlestickChart } from "./CandlestickChart";
import { MACDChart } from "./MACDChart";
import ElderRayChart from "./ElderRayChart";
import ForceIndexChart from "./ForceIndexChart";
import SignalPanel from "@/components/panels/SignalPanel";
import { useCandles } from "@/hooks/useCandles";
import { useIndicators } from "@/hooks/useIndicators";
import { fetchScreenConfig, type ScreenConfig, type CandleData, type IndicatorData } from "@/lib/api";
import { Loader2, Maximize2, Minimize2 } from "lucide-react";

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
  height: number;
  screen: number;
}

// ── Shared screen header with zoom button ─────────────────────

function ScreenHeader({
  label,
  source,
  barCount,
  zoomed,
  onZoom,
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

// ── Screen 1 (Tide) ───────────────────────────────────────────

function Screen1Panel({
  symbol, exchange, label, interval, days, height, zoomed, onZoom,
}: {
  symbol: string; exchange: string; label: string;
  interval: string; days: number; height: number;
  zoomed: boolean; onZoom: () => void;
}) {
  const { candles, loading, error, source } = useCandles(symbol, exchange, interval, days);
  const { data: indicators } = useIndicators(symbol, exchange, interval, days, 1);

  const chartH = zoomed ? 420 : height;
  const macdH = zoomed ? 150 : 100;
  const placeholderH = chartH + macdH + 20;

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
      ) : (
        <>
          <CandlestickChart candles={candles} indicators={indicators} height={chartH} showVolume={zoomed} />
          <MACDChart candles={candles} indicators={indicators} height={macdH} />
        </>
      )}
    </div>
  );
}

// ── Screen 2 (Wave) ───────────────────────────────────────────

function Screen2Panel({
  symbol, exchange, label, interval, days, height, zoomed, onZoom, onDataLoaded,
}: {
  symbol: string; exchange: string; label: string;
  interval: string; days: number; height: number;
  zoomed: boolean; onZoom: () => void;
  onDataLoaded?: (candles: CandleData[], indicators: IndicatorData | null) => void;
}) {
  const { candles, loading, error, source } = useCandles(symbol, exchange, interval, days);
  const { data: indicators } = useIndicators(symbol, exchange, interval, days, 2);

  useEffect(() => {
    if (onDataLoaded && candles.length > 0) {
      onDataLoaded(candles, indicators ?? null);
    }
  }, [candles, indicators, onDataLoaded]);

  const timestamps = indicators?.timestamps ?? [];
  const chartH = zoomed ? 400 : height;
  const macdH = zoomed ? 140 : 90;
  const fiH = zoomed ? 120 : 80;
  const erH = zoomed ? 120 : 80;
  const placeholderH = chartH + macdH + fiH + erH + 20;

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
      ) : (
        <>
          <CandlestickChart candles={candles} indicators={indicators} height={chartH} showVolume={zoomed} />
          <MACDChart candles={candles} indicators={indicators} height={macdH} />
          <ForceIndexChart
            timestamps={timestamps}
            forceIndex2={indicators?.force_index_2 ?? undefined}
            forceIndex13={indicators?.force_index ?? undefined}
            height={fiH}
          />
          <ElderRayChart
            timestamps={timestamps}
            bullPower={indicators?.elder_ray_bull ?? []}
            bearPower={indicators?.elder_ray_bear ?? []}
            height={erH}
          />
        </>
      )}
    </div>
  );
}

// ── Screen 3 (Ripple) ─────────────────────────────────────────

function Screen3Panel({
  symbol, exchange, label, interval, days, height, zoomed, onZoom,
}: {
  symbol: string; exchange: string; label: string;
  interval: string; days: number; height: number;
  zoomed: boolean; onZoom: () => void;
}) {
  const { candles, loading, error, source } = useCandles(symbol, exchange, interval, days);
  const { data: indicators } = useIndicators(symbol, exchange, interval, days, 3);

  const timestamps = indicators?.timestamps ?? [];
  const chartH = zoomed ? 420 : height;
  const fiH = zoomed ? 140 : 80;
  const placeholderH = chartH + fiH + 20;

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
      ) : (
        <>
          <CandlestickChart candles={candles} indicators={indicators} height={chartH} showVolume={zoomed} />
          <ForceIndexChart
            timestamps={timestamps}
            forceIndex2={indicators?.force_index_2 ?? undefined}
            height={fiH}
          />
        </>
      )}
    </div>
  );
}

// ── Screen config ─────────────────────────────────────────────

function getDefaultScreens(exchange: string): ScreenDef[] {
  if (exchange === "NFO" || exchange === "MCX") {
    return [
      { label: "Screen 1 — Daily (Tide)", interval: "1d", days: 365, height: 220, screen: 1 },
      { label: "Screen 2 — Hourly (Wave)", interval: "1h", days: 90, height: 200, screen: 2 },
      { label: "Screen 3 — 15min (Ripple)", interval: "15m", days: 30, height: 200, screen: 3 },
    ];
  }
  return [
    { label: "Screen 1 — Weekly (Tide)", interval: "1w", days: 730, height: 220, screen: 1 },
    { label: "Screen 2 — Daily (Wave)", interval: "1d", days: 365, height: 200, screen: 2 },
    { label: "Screen 3 — Intraday (Ripple)", interval: "15m", days: 30, height: 200, screen: 3 },
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
            interval: s1tf, days: TF_DAYS[s1tf] ?? 365, height: 220, screen: 1,
          },
          {
            label: `Screen 2 — ${TF_LABELS[s2tf] ?? s2tf} (Wave)`,
            interval: s2tf, days: TF_DAYS[s2tf] ?? 365, height: 200, screen: 2,
          },
          {
            label: `Screen 3 — ${TF_LABELS[s3tf] ?? s3tf} (Ripple)`,
            interval: s3tf, days: TF_DAYS[s3tf] ?? 30, height: 200, screen: 3,
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
    const t2 = setTimeout(() => setShowScreen(2), 3000);
    const t3 = setTimeout(() => setShowScreen(3), 6000);
    return () => { clearTimeout(t2); clearTimeout(t3); };
  }, [symbol, exchange]);

  // Zoom state: null = all 3, 1/2/3 = zoomed into that screen
  const [zoomedScreen, setZoomedScreen] = useState<number | null>(null);

  // Screen 2 shares its data with SignalPanel
  const [s2Candles, setS2Candles] = useState<CandleData[]>([]);
  const [s2Indicators, setS2Indicators] = useState<IndicatorData | null>(null);
  const handleS2Data = useCallback((candles: CandleData[], indicators: IndicatorData | null) => {
    setS2Candles(candles);
    setS2Indicators(indicators);
  }, []);

  const toggleZoom = useCallback((screen: number) => {
    setZoomedScreen((prev) => (prev === screen ? null : screen));
  }, []);

  // Render a screen panel (zoomed or normal)
  const renderScreen = (screenIdx: number, zoomed: boolean) => {
    const def = screens[screenIdx];
    const onZoom = () => toggleZoom(screenIdx + 1);

    if (screenIdx === 0) {
      return (
        <Screen1Panel
          symbol={symbol} exchange={exchange}
          label={def.label} interval={def.interval} days={def.days} height={def.height}
          zoomed={zoomed} onZoom={onZoom}
        />
      );
    }
    if (screenIdx === 1) {
      return (
        <Screen2Panel
          symbol={symbol} exchange={exchange}
          label={def.label} interval={def.interval} days={def.days} height={def.height}
          zoomed={zoomed} onZoom={onZoom}
          onDataLoaded={handleS2Data}
        />
      );
    }
    return (
      <Screen3Panel
        symbol={symbol} exchange={exchange}
        label={def.label} interval={def.interval} days={def.days} height={def.height}
        zoomed={zoomed} onZoom={onZoom}
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
    <div className="flex flex-col gap-2">
      {zoomedScreen != null ? (
        /* ── Zoomed: single screen full-width ── */
        <div className="flex flex-col gap-2">
          {renderScreen(zoomedScreen - 1, true)}
        </div>
      ) : (
        /* ── Normal: 3-column grid ── */
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-2">
          {renderScreen(0, false)}
          {showScreen >= 2 ? renderScreen(1, false) : loadingPlaceholder(screens[1].height + 120)}
          {showScreen >= 3 ? renderScreen(2, false) : loadingPlaceholder(screens[2].height + 90)}
        </div>
      )}
      {/* Signal Analysis Panel */}
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
