"use client";

/**
 * Hook for Three Screen View — fetches initial data via REST
 * then receives live updates via WebSocket through the Zustand store.
 *
 * Each screen timeframe gets its own slice in screenData[tf].
 * The WebSocket manager routes candle/running_bar/indicators events
 * to the correct timeframe slot automatically.
 */

import { useEffect, useRef } from "react";
import { useTradingStore } from "@/store/useTradingStore";
import { fetchCandles, fetchWeekly, fetchIndicators } from "@/lib/api";
import type { CandleData, IndicatorData } from "@/lib/api";

interface UseScreenDataResult {
  candles: CandleData[];
  indicators: IndicatorData | null;
  runningBar: CandleData | null;
  loading: boolean;
  error: string | null;
  source: "live" | "demo" | null;
}

export function useScreenData(
  symbol: string,
  exchange: string,
  interval: string,
  days: number,
  screen?: number,
): UseScreenDataResult {
  const abortRef = useRef<AbortController | null>(null);
  const errorRef = useRef<string | null>(null);
  const sourceRef = useRef<"live" | "demo" | null>(null);

  // Read from Zustand store — this is live-updated by WebSocket
  const slice = useTradingStore((s) => s.screenData[interval]);

  // Fetch initial data via REST on mount or when symbol/interval changes
  useEffect(() => {
    if (!symbol) return;

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    errorRef.current = null;
    sourceRef.current = null;
    // Use getState() to avoid dependency on store actions (which change every render)
    const store = useTradingStore.getState();
    store.setScreenLoading(interval, true);

    const doFetch = async () => {
      try {
        const candleRes = interval === "1w"
          ? await fetchWeekly(symbol, exchange, days)
          : await fetchCandles(symbol, exchange, interval, days);

        if (ctrl.signal.aborted) return;

        if (candleRes.error || !candleRes.data || candleRes.data.length === 0) {
          errorRef.current = candleRes.error || "No data available";
          useTradingStore.getState().setScreenLoading(interval, false);
          return;
        }

        sourceRef.current = candleRes.source || "live";
        useTradingStore.getState().setScreenCandles(interval, candleRes.data);

        try {
          const indRes = await fetchIndicators(symbol, exchange, interval, days, screen);
          if (ctrl.signal.aborted) return;
          if (indRes.data) {
            useTradingStore.getState().setScreenIndicators(interval, indRes.data);
          }
        } catch {
          // Indicators are non-critical
        }
      } catch (e: any) {
        if (ctrl.signal.aborted) return;
        errorRef.current = e.message || "Failed to fetch data";
      } finally {
        if (!ctrl.signal.aborted) {
          useTradingStore.getState().setScreenLoading(interval, false);
        }
      }
    };

    doFetch();
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, exchange, interval, days, screen]);

  return {
    candles: slice?.candles ?? [],
    indicators: slice?.indicators ?? null,
    runningBar: slice?.runningBar ?? null,
    loading: slice?.loading ?? true,
    error: errorRef.current,
    source: sourceRef.current,
  };
}
