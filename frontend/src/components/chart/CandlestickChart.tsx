"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  ColorType,
  CrosshairMode,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type Time,
  LineStyle,
  type IPriceLine,
} from "lightweight-charts";
import type { CandleData, IndicatorData } from "@/lib/api";
import { useTheme } from "@/hooks/useTheme";
import { getChartTheme } from "@/lib/chartTheme";

interface CandlestickChartProps {
  candles: CandleData[];
  indicators?: IndicatorData | null;
  height?: number;
  showVolume?: boolean;
}

function toTime(ts: string): Time {
  return (new Date(ts).getTime() / 1000) as Time;
}

// Map impulse colors to hex
const IMPULSE_MAP: Record<string, { up: string; down: string; wickUp: string; wickDown: string }> = {
  green: { up: "#22c55e", down: "#22c55e", wickUp: "#22c55e88", wickDown: "#22c55e88" },
  red: { up: "#ef4444", down: "#ef4444", wickUp: "#ef444488", wickDown: "#ef444488" },
  blue: { up: "#6366f1", down: "#6366f1", wickUp: "#6366f188", wickDown: "#6366f188" },
};

export function CandlestickChart({
  candles,
  indicators,
  height = 500,
  showVolume = true,
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRefs = useRef<Record<string, any>>({});
  const priceLineRef = useRef<IPriceLine | null>(null);
  const prevCountRef = useRef(0);
  const { theme } = useTheme();

  // Create chart once
  useEffect(() => {
    if (!containerRef.current) return;
    const ct = getChartTheme();

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: ct.bg },
        textColor: ct.text,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: ct.grid },
        horzLines: { color: ct.grid },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: ct.accent + "80", width: 1, style: 2 },
        horzLine: { color: ct.accent + "80", width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: ct.border,
        scaleMargins: { top: 0.05, bottom: showVolume ? 0.25 : 0.05 },
      },
      timeScale: {
        borderColor: ct.border,
        timeVisible: true,
        secondsVisible: false,
      },
    });

    // Candlestick series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e88",
      wickDownColor: "#ef444488",
    });
    seriesRefs.current.candles = candleSeries;

    // Volume
    if (showVolume) {
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      seriesRefs.current.volume = volumeSeries;
    }

    // EMA-13 line
    const ema13Series = chart.addSeries(LineSeries, {
      color: "#f59e0b",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    seriesRefs.current.ema13 = ema13Series;

    // EMA-22 line
    const ema22Series = chart.addSeries(LineSeries, {
      color: "#8b5cf6",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    seriesRefs.current.ema22 = ema22Series;

    // SafeZone long (support) — green dashed
    const szLongSeries = chart.addSeries(LineSeries, {
      color: "#22c55e60",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    seriesRefs.current.szLong = szLongSeries;

    // SafeZone short (resistance) — red dashed
    const szShortSeries = chart.addSeries(LineSeries, {
      color: "#ef444460",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    seriesRefs.current.szShort = szShortSeries;

    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
      seriesRefs.current = {};
    };
  }, [height, showVolume, theme]);

  // Update data when candles or indicators change
  useEffect(() => {
    const refs = seriesRefs.current;
    if (!refs.candles || candles.length === 0) return;

    // Build candle data with optional impulse coloring
    const hasImpulse = indicators?.impulse_color && indicators.impulse_color.length > 0;

    const candleData: CandlestickData[] = candles.map((c, i) => {
      const base: CandlestickData = {
        time: toTime(c.timestamp),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      };

      // Color candles by impulse system
      if (hasImpulse && indicators?.impulse_color[i]) {
        const impulseColor = indicators.impulse_color[i] as string;
        const colors = IMPULSE_MAP[impulseColor];
        if (colors) {
          return {
            ...base,
            color: colors.up,
            borderColor: colors.up,
            wickColor: colors.wickUp,
          };
        }
      }

      return base;
    });

    refs.candles.setData(candleData);

    // Volume (colored by impulse if available)
    if (refs.volume) {
      const volData: HistogramData[] = candles.map((c, i) => {
        let color = c.close >= c.open ? "#22c55e40" : "#ef444440";
        if (hasImpulse && indicators?.impulse_color[i]) {
          const ic = indicators.impulse_color[i];
          if (ic === "green") color = "#22c55e40";
          else if (ic === "red") color = "#ef444440";
          else color = "#6366f130";
        }
        return { time: toTime(c.timestamp), value: c.volume, color };
      });
      refs.volume.setData(volData);
    }

    // Include ALL timestamps for overlays so logical indices match
    const lineData = (arr?: (number | null)[]): LineData[] => {
      if (!arr) return [];
      return candles.map((c, i) => ({
        time: toTime(c.timestamp),
        value: (arr[i] ?? 0) as number,
      }));
    };

    // EMA-13 overlay
    if (refs.ema13) refs.ema13.setData(lineData(indicators?.ema13));

    // EMA-22 overlay
    if (refs.ema22) refs.ema22.setData(lineData(indicators?.ema22));

    // SafeZone support (long stop)
    if (refs.szLong) refs.szLong.setData(lineData(indicators?.safezone_long));

    // SafeZone resistance (short stop)
    if (refs.szShort) refs.szShort.setData(lineData(indicators?.safezone_short));

    // Only fit content on initial load / symbol change, not every tick
    if (candles.length !== prevCountRef.current) {
      chartRef.current?.timeScale().fitContent();
      prevCountRef.current = candles.length;
    }

    // LTP price line on last candle
    if (candles.length > 0 && refs.candles) {
      const lastClose = candles[candles.length - 1].close;
      try {
        if (priceLineRef.current) {
          refs.candles.removePriceLine(priceLineRef.current);
        }
        priceLineRef.current = refs.candles.createPriceLine({
          price: lastClose,
          color: "#2962FF",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: "",
        });
      } catch { /* series may be disposed */ }
    }
  }, [candles, indicators, height, showVolume]);

  return (
    <div
      ref={containerRef}
      className="w-full rounded border border-border overflow-hidden"
      style={{ height }}
    />
  );
}
