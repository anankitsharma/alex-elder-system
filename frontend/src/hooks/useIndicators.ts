"use client";

import { useState, useEffect, useRef } from "react";
import { fetchIndicators, type IndicatorData } from "@/lib/api";

export function useIndicators(
  symbol: string,
  exchange: string,
  interval: string,
  days = 365,
  screen?: number
) {
  const [data, setData] = useState<IndicatorData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!symbol) return;

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setLoading(true);
    setError(null);

    fetchIndicators(symbol, exchange, interval, days, screen)
      .then((res) => {
        if (ctrl.signal.aborted) return;
        if (res.error) {
          setError(res.error);
          setData(null);
        } else {
          setData(res.data);
        }
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setError(err.message);
        setData(null);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });

    return () => ctrl.abort();
  }, [symbol, exchange, interval, days, screen]);

  return { data, loading, error };
}
