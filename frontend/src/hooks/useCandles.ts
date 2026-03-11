"use client";

import { useEffect, useState, useRef } from "react";
import { fetchCandles, fetchWeekly, type CandleData } from "@/lib/api";

interface UseCandlesResult {
  candles: CandleData[];
  loading: boolean;
  error: string | null;
  source: "live" | "demo" | null;
  refetch: () => void;
}

export function useCandles(
  symbol: string,
  exchange = "NSE",
  interval = "1d",
  days = 365
): UseCandlesResult {
  const [candles, setCandles] = useState<CandleData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<"live" | "demo" | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [fetchKey, setFetchKey] = useState(0);

  useEffect(() => {
    if (!symbol) return;

    // Abort previous in-flight request (handles React Strict Mode double-mount)
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setLoading(true);
    setError(null);

    const doFetch = async () => {
      try {
        const res =
          interval === "1w"
            ? await fetchWeekly(symbol, exchange, days)
            : await fetchCandles(symbol, exchange, interval, days);

        if (ctrl.signal.aborted) return;

        if (res.error) {
          setError(res.error);
          setCandles([]);
          setSource(null);
        } else if (!res.data || res.data.length === 0) {
          setError("No data available");
          setCandles([]);
          setSource(null);
        } else {
          setCandles(res.data);
          setSource(res.source || "live");
        }
      } catch (e: any) {
        if (ctrl.signal.aborted) return;
        setError(e.message || "Failed to fetch data");
        setCandles([]);
        setSource(null);
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    };

    doFetch();

    return () => ctrl.abort();
  }, [symbol, exchange, interval, days, fetchKey]);

  const refetch = () => setFetchKey((k) => k + 1);

  return { candles, loading, error, source, refetch };
}
