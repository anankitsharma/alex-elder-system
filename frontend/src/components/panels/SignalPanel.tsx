"use client";

import { useState, useEffect, useCallback } from "react";
import {
  analyzeTripleScreen,
  fetchScreenConfig,
  type TripleScreenResult,
  type ScreenConfig,
  type CandleData,
  type IndicatorData,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { RefreshCw, AlertTriangle, ShieldCheck, ShieldAlert } from "lucide-react";

interface SignalPanelProps {
  symbol: string;
  exchange: string;
  candles: CandleData[];
  indicators: IndicatorData | null;
}

const TIDE_COLORS: Record<string, string> = {
  BULLISH: "text-green",
  BEARISH: "text-red",
  NEUTRAL: "text-muted",
};

const GRADE_COLORS: Record<string, string> = {
  A: "bg-green/20 text-green border-green/30",
  B: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  C: "bg-amber/20 text-amber border-amber/30",
  D: "bg-red/20 text-red border-red/30",
};

const ACTION_COLORS: Record<string, string> = {
  BUY: "bg-green/20 text-green",
  SELL: "bg-red/20 text-red",
  WAIT: "bg-zinc-700/50 text-muted",
};

const TF_LABELS: Record<string, string> = {
  "1w": "Weekly",
  "1d": "Daily",
  "4h": "4H",
  "1h": "Hourly",
  "15m": "15min",
  "5m": "5min",
};

export default function SignalPanel({ symbol, exchange, candles, indicators }: SignalPanelProps) {
  const [result, setResult] = useState<TripleScreenResult | null>(null);
  const [config, setConfig] = useState<ScreenConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch screen config when symbol changes
  useEffect(() => {
    if (!symbol) return;
    fetchScreenConfig(symbol, exchange)
      .then(setConfig)
      .catch(() => setConfig(null));
  }, [symbol, exchange]);

  const runAnalysis = useCallback(async () => {
    if (!candles.length || !indicators) return;

    setLoading(true);
    setError(null);

    try {
      const res = await analyzeTripleScreen({
        candles: candles.map((c) => ({
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
          volume: c.volume,
        })),
        indicators: {
          ema13: indicators.ema13,
          macd_histogram: indicators.macd_histogram,
          force_index_2: indicators.force_index_2,
          elder_ray_bull: indicators.elder_ray_bull,
          elder_ray_bear: indicators.elder_ray_bear,
          impulse_signal: indicators.impulse_signal,
          value_zone_fast: indicators.value_zone_fast,
          value_zone_slow: indicators.value_zone_slow,
          safezone_long: indicators.safezone_long,
          safezone_short: indicators.safezone_short,
        },
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }, [candles, indicators]);

  // Auto-run when data changes
  useEffect(() => {
    if (candles.length > 0 && indicators) {
      runAnalysis();
    }
  }, [candles.length, indicators, runAnalysis]);

  return (
    <div className="flex flex-col gap-2 p-2 text-xs">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="font-semibold text-[11px] text-foreground">Triple Screen Analysis</span>
        <button
          onClick={runAnalysis}
          disabled={loading || !candles.length}
          className="p-1 rounded hover:bg-surface-hover text-muted disabled:opacity-30"
          title="Refresh analysis"
        >
          <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
        </button>
      </div>

      {/* Asset Class & Timeframe Info */}
      {config && (
        <div className="flex items-center gap-1.5 text-[10px]">
          <span className="px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-400 font-medium">
            {config.asset_class}
          </span>
          {Object.entries(config.screens).map(([num, s]) => (
            <span key={num} className="text-muted">
              S{num}: {TF_LABELS[s.timeframe] ?? s.timeframe}
            </span>
          ))}
        </div>
      )}

      {error && (
        <div className="text-[10px] text-red px-1">{error}</div>
      )}

      {!result && !loading && !error && (
        <div className="text-[10px] text-muted px-1">Waiting for data...</div>
      )}

      {result && (
        <>
          {/* Recommendation + Grade */}
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "px-2 py-1 rounded text-[11px] font-bold uppercase",
                ACTION_COLORS[result.recommendation.action] ?? ACTION_COLORS.WAIT
              )}
            >
              {result.recommendation.action}
            </span>
            <span
              className={cn(
                "px-1.5 py-0.5 rounded border text-[10px] font-bold",
                GRADE_COLORS[result.grade] ?? GRADE_COLORS.D
              )}
            >
              Grade {result.grade}
            </span>
            <div className="flex-1" />
            <span className="text-muted text-[10px]">
              {result.recommendation.confidence}% confidence
            </span>
          </div>

          {/* Confidence bar */}
          <div className="h-1 w-full bg-zinc-800 rounded overflow-hidden">
            <div
              className={cn(
                "h-full rounded transition-all",
                result.recommendation.confidence >= 70 ? "bg-green" :
                result.recommendation.confidence >= 40 ? "bg-amber" : "bg-red"
              )}
              style={{ width: `${result.recommendation.confidence}%` }}
            />
          </div>

          {/* Screen 1: Tide */}
          <div className="bg-surface rounded p-1.5 border border-border">
            <div className="flex items-center justify-between">
              <span className="text-muted text-[10px]">Screen 1 &mdash; Tide</span>
              <span className={cn("font-semibold text-[11px]", TIDE_COLORS[result.screen1.tide])}>
                {result.screen1.tide}
              </span>
            </div>
            <div className="flex items-center gap-2 mt-0.5 text-[10px] text-muted">
              <span>MACD-H slope: {result.screen1.macd_histogram_slope > 0 ? "+" : ""}{result.screen1.macd_histogram_slope.toFixed(2)}</span>
              <span>EMA: {result.screen1.ema_trend}</span>
              <span>Impulse: {result.screen1.impulse_signal}</span>
              {result.screen1.impulse_confirms && (
                <span className="text-green">confirmed</span>
              )}
            </div>
          </div>

          {/* Screen 2: Wave */}
          <div className="bg-surface rounded p-1.5 border border-border">
            <div className="flex items-center justify-between">
              <span className="text-muted text-[10px]">Screen 2 &mdash; Wave</span>
              <span className={cn(
                "font-semibold text-[11px]",
                result.screen2.signal === "BUY" ? "text-green" :
                result.screen2.signal === "SELL" ? "text-red" : "text-muted"
              )}>
                {result.screen2.signal}
              </span>
            </div>
            {result.screen2.reasons.length > 0 && (
              <ul className="mt-0.5 text-[10px] text-muted space-y-0.5">
                {result.screen2.reasons.map((r, i) => (
                  <li key={i} className="flex items-start gap-1">
                    <span className="text-green mt-px">&#x2022;</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Screen 3: Entry */}
          {result.screen3.entry_type !== "MARKET" && result.screen3.entry_type !== "NONE" && (
            <div className="bg-surface rounded p-1.5 border border-border">
              <div className="flex items-center justify-between">
                <span className="text-muted text-[10px]">Screen 3 &mdash; Entry</span>
                <span className="font-semibold text-[11px] text-foreground">
                  {result.screen3.entry_type}
                </span>
              </div>
              <div className="flex items-center gap-3 mt-0.5 text-[10px]">
                {result.screen3.entry_price != null && (
                  <span className="text-foreground">
                    Entry: <span className="font-mono">{result.screen3.entry_price.toFixed(2)}</span>
                  </span>
                )}
                {result.screen3.stop_price != null && (
                  <span className="text-red">
                    Stop: <span className="font-mono">{result.screen3.stop_price.toFixed(2)}</span>
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Reason */}
          <div className="text-[10px] text-muted px-0.5">
            {result.recommendation.reason}
          </div>

          {/* Validation */}
          {result.validation && (
            <div className="flex flex-col gap-0.5">
              {result.validation.is_valid ? (
                <div className="flex items-center gap-1 text-[10px] text-green">
                  <ShieldCheck className="w-3 h-3" />
                  <span>Cross-timeframe validation passed</span>
                </div>
              ) : (
                <div className="flex items-center gap-1 text-[10px] text-red">
                  <ShieldAlert className="w-3 h-3" />
                  <span>Validation blocked</span>
                </div>
              )}
              {result.validation.blocks.map((b, i) => (
                <div key={i} className="flex items-start gap-1 text-[10px] text-red pl-4">
                  <span>&#x2717;</span> <span>{b}</span>
                </div>
              ))}
              {result.validation.warnings.map((w, i) => (
                <div key={i} className="flex items-start gap-1 text-[10px] text-amber pl-4">
                  <AlertTriangle className="w-3 h-3 mt-px flex-shrink-0" />
                  <span>{w}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
