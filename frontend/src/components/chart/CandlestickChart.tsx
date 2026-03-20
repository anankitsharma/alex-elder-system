"use client";

import { useEffect, useRef, useState } from "react";
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

interface OHLCVLegend {
  o: number; h: number; l: number; c: number; v: number;
  change: number; pct: number;
}

function toTime(ts: string): Time {
  return (new Date(ts).getTime() / 1000) as Time;
}

const IMPULSE_MAP: Record<string, { up: string; down: string; wickUp: string; wickDown: string }> = {
  green: { up: "#22c55e", down: "#22c55e", wickUp: "#22c55e88", wickDown: "#22c55e88" },
  red: { up: "#ef4444", down: "#ef4444", wickUp: "#ef444488", wickDown: "#ef444488" },
  blue: { up: "#6366f1", down: "#6366f1", wickUp: "#6366f188", wickDown: "#6366f188" },
};

const fmt = (n: number) => {
  if (n >= 1e7) return (n / 1e7).toFixed(2) + "Cr";
  if (n >= 1e5) return (n / 1e5).toFixed(2) + "L";
  if (n >= 1000) return (n / 1000).toFixed(1) + "K";
  return n.toFixed(0);
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
  const [legend, setLegend] = useState<OHLCVLegend | null>(null);

  // Create chart
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
        vertLine: { color: ct.accent + "80", width: 1, style: 2, labelVisible: true },
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
        rightOffset: 10,
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e", downColor: "#ef4444",
      borderUpColor: "#22c55e", borderDownColor: "#ef4444",
      wickUpColor: "#22c55e88", wickDownColor: "#ef444488",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    seriesRefs.current.candles = candleSeries;

    if (showVolume) {
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
        lastValueVisible: false,
      });
      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      seriesRefs.current.volume = volumeSeries;
    }

    seriesRefs.current.ema13 = chart.addSeries(LineSeries, {
      color: "#f59e0b", lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
    });
    seriesRefs.current.ema22 = chart.addSeries(LineSeries, {
      color: "#8b5cf6", lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
    });
    seriesRefs.current.szLong = chart.addSeries(LineSeries, {
      color: "#22c55e60", lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false,
    });
    seriesRefs.current.szShort = chart.addSeries(LineSeries, {
      color: "#ef444460", lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false,
    });

    // OHLCV legend on crosshair
    const volSeries = seriesRefs.current.volume;
    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData) { setLegend(null); return; }
      const cd = param.seriesData.get(candleSeries) as CandlestickData | undefined;
      const vd = volSeries ? param.seriesData.get(volSeries) as HistogramData | undefined : undefined;
      if (cd) {
        const change = cd.close - cd.open;
        setLegend({
          o: cd.open, h: cd.high, l: cd.low, c: cd.close,
          v: vd?.value ?? 0, change, pct: cd.open ? (change / cd.open) * 100 : 0,
        });
      }
    });

    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
      seriesRefs.current = {};
    };
  }, [height, showVolume, theme]);

  // Update data — only full setData on initial load or count change
  const lastSetCountRef = useRef(0);

  useEffect(() => {
    const refs = seriesRefs.current;
    if (!refs.candles || candles.length === 0) return;

    try {

    const hasImpulse = indicators?.impulse_color && indicators.impulse_color.length > 0;

    if (candles.length !== lastSetCountRef.current) {
      const candleData: CandlestickData[] = candles.map((c, i) => {
        const base: CandlestickData = {
          time: toTime(c.timestamp), open: c.open, high: c.high, low: c.low, close: c.close,
        };
        if (hasImpulse && indicators?.impulse_color[i]) {
          const colors = IMPULSE_MAP[indicators.impulse_color[i] as string];
          if (colors) return { ...base, color: colors.up, borderColor: colors.up, wickColor: colors.wickUp };
        }
        return base;
      });
      refs.candles.setData(candleData);

      if (refs.volume) {
        const volData: HistogramData[] = candles.map((c, i) => {
          let color = c.close >= c.open ? "#22c55e40" : "#ef444440";
          if (hasImpulse && indicators?.impulse_color[i]) {
            const ic = indicators.impulse_color[i];
            color = ic === "green" ? "#22c55e40" : ic === "red" ? "#ef444440" : "#6366f130";
          }
          return { time: toTime(c.timestamp), value: c.volume, color };
        });
        refs.volume.setData(volData);
      }

      lastSetCountRef.current = candles.length;
    }

    // Overlays are on the SAME chart as candles — skip nulls (don't pad with 0,
    // which would pull the y-axis scale down to zero and squish the candles)
    const lineData = (arr?: (number | null)[]): LineData[] => {
      if (!arr) return [];
      const out: LineData[] = [];
      for (let i = 0; i < candles.length && i < arr.length; i++) {
        if (arr[i] != null) out.push({ time: toTime(candles[i].timestamp), value: arr[i] as number });
      }
      return out;
    };

    if (refs.ema13) refs.ema13.setData(lineData(indicators?.ema13));
    if (refs.ema22) refs.ema22.setData(lineData(indicators?.ema22));
    if (refs.szLong) refs.szLong.setData(lineData(indicators?.safezone_long));
    if (refs.szShort) refs.szShort.setData(lineData(indicators?.safezone_short));

    // Only fitContent on initial load (0→N) or big symbol change, not every update
    const isInit = prevCountRef.current === 0 && candles.length > 0;
    const isBigChange = candles.length > 0 && Math.abs(candles.length - prevCountRef.current) > 5;
    if (isInit || isBigChange) {
      chartRef.current?.timeScale().fitContent();
    }
    prevCountRef.current = candles.length;

    // LTP price line
    if (candles.length > 0 && refs.candles) {
      const lastClose = candles[candles.length - 1].close;
      try {
        if (priceLineRef.current) refs.candles.removePriceLine(priceLineRef.current);
        priceLineRef.current = refs.candles.createPriceLine({
          price: lastClose, color: "#2962FF", lineWidth: 1,
          lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "",
        });
      } catch { /* disposed */ }
    }

    } catch { /* lightweight-charts setData conflict — safe to ignore */ }
  }, [candles, indicators, height, showVolume]);

  // Display legend
  const d = legend ?? (candles.length > 0 ? (() => {
    const last = candles[candles.length - 1];
    const ch = last.close - last.open;
    return { o: last.open, h: last.high, l: last.low, c: last.close, v: last.volume, change: ch, pct: last.open ? (ch / last.open) * 100 : 0 };
  })() : null);
  const isUp = d ? d.c >= d.o : true;
  const clr = isUp ? "#22c55e" : "#ef4444";

  return (
    <div className="relative w-full rounded border border-border overflow-hidden" style={{ height }}>
      {/* TradingView-style OHLCV legend */}
      {d && (
        <div className="absolute top-0.5 left-2 z-10 flex items-center gap-1.5 text-[9px] font-mono pointer-events-none select-none">
          <span className="text-muted">O</span><span style={{ color: clr }}>{d.o.toFixed(2)}</span>
          <span className="text-muted">H</span><span style={{ color: clr }}>{d.h.toFixed(2)}</span>
          <span className="text-muted">L</span><span style={{ color: clr }}>{d.l.toFixed(2)}</span>
          <span className="text-muted">C</span><span style={{ color: clr }}>{d.c.toFixed(2)}</span>
          <span style={{ color: clr, fontSize: "8px" }}>
            {d.change >= 0 ? "+" : ""}{d.change.toFixed(2)} ({d.pct >= 0 ? "+" : ""}{d.pct.toFixed(2)}%)
          </span>
          {d.v > 0 && <span className="text-muted">{fmt(d.v)}</span>}
        </div>
      )}
      <div ref={containerRef} className="absolute inset-0" />
    </div>
  );
}
