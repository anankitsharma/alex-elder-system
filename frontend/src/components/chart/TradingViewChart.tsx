"use client";

/**
 * TradingView-style multi-pane chart.
 *
 * Layout (top to bottom):
 *   Main pane — Candlesticks + Volume + EMA + SafeZone + Impulse coloring
 *   MACD pane — Histogram (4-color) + MACD line + Signal line
 *   Force Index pane — FI-2 histogram + FI-13 line
 *   Elder-Ray pane — Bull Power + Bear Power histograms
 *
 * All panes share the same time axis (synced scroll/zoom/crosshair).
 * Only the bottom-most pane shows the time axis.
 */

import { useEffect, useRef, useCallback, useMemo } from "react";
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
  type LogicalRange,
  LineStyle,
} from "lightweight-charts";
import type { CandleData, IndicatorData } from "@/lib/api";
import { useTheme } from "@/hooks/useTheme";
import { getChartTheme } from "@/lib/chartTheme";

/* ── props ──────────────────────────────────────────────────────── */

interface TradingViewChartProps {
  candles: CandleData[];
  indicators?: IndicatorData | null;
  /** Show volume overlay on main chart */
  showVolume?: boolean;
  /** Show MACD sub-pane */
  showMACD?: boolean;
  /** Show Force Index sub-pane */
  showForceIndex?: boolean;
  /** Show Elder-Ray sub-pane */
  showElderRay?: boolean;
}

/* ── constants ──────────────────────────────────────────────────── */

const IMPULSE_MAP: Record<string, { body: string; wick: string }> = {
  green:  { body: "#22c55e", wick: "#22c55e88" },
  red:    { body: "#ef4444", wick: "#ef444488" },
  blue:   { body: "#6366f1", wick: "#6366f188" },
};

function toTime(ts: string): Time {
  return (new Date(ts).getTime() / 1000) as Time;
}

/* ── component ──────────────────────────────────────────────────── */

export default function TradingViewChart({
  candles,
  indicators,
  showVolume = true,
  showMACD = true,
  showForceIndex = true,
  showElderRay = true,
}: TradingViewChartProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Refs for each pane's container div
  const mainRef = useRef<HTMLDivElement>(null);
  const macdRef = useRef<HTMLDivElement>(null);
  const fiRef   = useRef<HTMLDivElement>(null);
  const erRef   = useRef<HTMLDivElement>(null);

  // Chart instances
  const chartsRef = useRef<IChartApi[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef = useRef<Record<string, any>>({});
  const syncingRef = useRef(false);
  const prevCandleCountRef = useRef(0);
  const { theme: currentTheme } = useTheme();

  /* ── determine which sub-panes are active ────────────────────── */
  const hasMACD = showMACD && indicators?.macd_histogram?.some((v) => v != null);
  const hasFI = showForceIndex && (
    indicators?.force_index_2?.some((v) => v != null) ||
    indicators?.force_index?.some((v) => v != null)
  );
  const hasER = showElderRay && indicators?.elder_ray_bull?.some((v) => v != null);

  /* ── chart creation ──────────────────────────────────────────── */

  const buildCharts = useCallback(() => {
    // Clean up old
    chartsRef.current.forEach((c) => c.remove());
    chartsRef.current = [];
    seriesRef.current = {};

    const containerWidth = wrapperRef.current?.clientWidth ?? 800;
    const ct = getChartTheme();

    // Collect panes: [container, isLast, height]
    type Pane = { el: HTMLDivElement; last: boolean; };
    const panes: Pane[] = [];

    if (mainRef.current) panes.push({ el: mainRef.current, last: false });
    if (hasMACD && macdRef.current) panes.push({ el: macdRef.current, last: false });
    if (hasFI && fiRef.current) panes.push({ el: fiRef.current, last: false });
    if (hasER && erRef.current) panes.push({ el: erRef.current, last: false });

    if (panes.length > 0) panes[panes.length - 1].last = true;

    const crossColor = ct.accent + "80";
    const crossColorDim = ct.accent + "40";

    const sharedOpts = {
      layout: {
        background: { type: ColorType.Solid as const, color: ct.bg },
        textColor: ct.text,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: ct.grid },
        horzLines: { color: ct.grid },
      },
      rightPriceScale: {
        borderColor: ct.border,
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      handleScroll: { vertTouchDrag: false },
    };

    const charts: IChartApi[] = [];

    for (const pane of panes) {
      const isMain = pane.el === mainRef.current;
      const h = pane.el.clientHeight || (isMain ? 400 : 100);

      const chart = createChart(pane.el, {
        ...sharedOpts,
        width: containerWidth,
        height: h,
        crosshair: isMain
          ? {
              mode: CrosshairMode.Normal,
              vertLine: { color: crossColor, width: 1, style: 2, labelVisible: false },
              horzLine: { color: crossColor, width: 1, style: 2 },
            }
          : {
              mode: CrosshairMode.Normal,
              vertLine: { color: crossColor, width: 1, style: 2, labelVisible: false },
              horzLine: { color: crossColorDim, width: 1, style: 2 },
            },
        rightPriceScale: {
          ...sharedOpts.rightPriceScale,
          scaleMargins: isMain
            ? { top: 0.02, bottom: showVolume ? 0.22 : 0.02 }
            : { top: 0.15, bottom: 0.1 },
        },
        timeScale: {
          borderColor: ct.border,
          visible: pane.last,
          timeVisible: true,
          secondsVisible: false,
        },
      });

      // ── Create series per pane ──
      if (isMain) {
        // Candlesticks
        const cs = chart.addSeries(CandlestickSeries, {
          upColor: "#22c55e", downColor: "#ef4444",
          borderUpColor: "#22c55e", borderDownColor: "#ef4444",
          wickUpColor: "#22c55e88", wickDownColor: "#ef444488",
        });
        seriesRef.current.candles = cs;

        // Volume
        if (showVolume) {
          const vol = chart.addSeries(HistogramSeries, {
            priceFormat: { type: "volume" },
            priceScaleId: "vol",
          });
          chart.priceScale("vol").applyOptions({
            scaleMargins: { top: 0.8, bottom: 0 },
          });
          seriesRef.current.volume = vol;
        }

        // EMA-13
        seriesRef.current.ema13 = chart.addSeries(LineSeries, {
          color: "#f59e0b", lineWidth: 1,
          priceLineVisible: false, lastValueVisible: false,
        });
        // EMA-22
        seriesRef.current.ema22 = chart.addSeries(LineSeries, {
          color: "#8b5cf6", lineWidth: 1,
          priceLineVisible: false, lastValueVisible: false,
        });
        // SafeZone long
        seriesRef.current.szLong = chart.addSeries(LineSeries, {
          color: "#22c55e50", lineWidth: 1, lineStyle: LineStyle.Dashed,
          priceLineVisible: false, lastValueVisible: false,
        });
        // SafeZone short
        seriesRef.current.szShort = chart.addSeries(LineSeries, {
          color: "#ef444450", lineWidth: 1, lineStyle: LineStyle.Dashed,
          priceLineVisible: false, lastValueVisible: false,
        });
      }

      if (pane.el === macdRef.current) {
        seriesRef.current.macdHist = chart.addSeries(HistogramSeries, {
          priceFormat: { type: "price", precision: 2 },
          priceLineVisible: false, lastValueVisible: false,
        });
        seriesRef.current.macdLine = chart.addSeries(LineSeries, {
          color: "#2962FF", lineWidth: 1,
          priceLineVisible: false, lastValueVisible: false,
        });
        seriesRef.current.macdSignal = chart.addSeries(LineSeries, {
          color: "#FF6D00", lineWidth: 1,
          priceLineVisible: false, lastValueVisible: false,
        });
      }

      if (pane.el === fiRef.current) {
        seriesRef.current.fi2 = chart.addSeries(HistogramSeries, {
          priceFormat: { type: "price", precision: 0 },
          priceLineVisible: false, lastValueVisible: false,
        });
        seriesRef.current.fi13 = chart.addSeries(LineSeries, {
          color: "#f59e0b", lineWidth: 1,
          priceLineVisible: false, lastValueVisible: false,
        });
      }

      if (pane.el === erRef.current) {
        seriesRef.current.erBull = chart.addSeries(HistogramSeries, {
          priceFormat: { type: "price", precision: 2 },
          priceLineVisible: false, lastValueVisible: false,
        });
        seriesRef.current.erBear = chart.addSeries(HistogramSeries, {
          priceFormat: { type: "price", precision: 2 },
          priceLineVisible: false, lastValueVisible: false,
        });
      }

      charts.push(chart);
    }

    // ── Sync visible range ──
    charts.forEach((chart, idx) => {
      chart.timeScale().subscribeVisibleLogicalRangeChange((range: LogicalRange | null) => {
        if (syncingRef.current || !range) return;
        syncingRef.current = true;
        charts.forEach((other, oidx) => {
          if (oidx !== idx) {
            other.timeScale().setVisibleLogicalRange(range);
          }
        });
        syncingRef.current = false;
      });
    });

    // ── Sync crosshair ──
    // Map each chart to its first series (setCrosshairPosition requires a series ref)
    const seriesForChart = charts.map((_, idx) => {
      const paneEl = panes[idx]?.el;
      if (paneEl === mainRef.current) return seriesRef.current.candles;
      if (paneEl === macdRef.current) return seriesRef.current.macdHist;
      if (paneEl === fiRef.current) return seriesRef.current.fi2;
      if (paneEl === erRef.current) return seriesRef.current.erBull;
      return null;
    });

    charts.forEach((chart, idx) => {
      chart.subscribeCrosshairMove((param) => {
        if (syncingRef.current) return;
        syncingRef.current = true;
        charts.forEach((other, oidx) => {
          if (oidx !== idx && seriesForChart[oidx]) {
            if (param.time) {
              other.setCrosshairPosition(NaN, param.time, seriesForChart[oidx]);
            } else {
              other.clearCrosshairPosition();
            }
          }
        });
        syncingRef.current = false;
      });
    });

    chartsRef.current = charts;
  }, [showVolume, hasMACD, hasFI, hasER, currentTheme]);

  /* ── init / destroy ──────────────────────────────────────────── */

  useEffect(() => {
    buildCharts();

    // ResizeObserver — updates chart width + main pane height on container resize
    const onResize = () => {
      if (!wrapperRef.current) return;
      const w = wrapperRef.current.clientWidth;
      chartsRef.current.forEach((c, idx) => {
        const h = idx === 0 && mainRef.current ? mainRef.current.clientHeight : undefined;
        c.applyOptions(h ? { width: w, height: h } : { width: w });
      });
    };

    const observer = new ResizeObserver(onResize);
    if (wrapperRef.current) observer.observe(wrapperRef.current);

    return () => {
      observer.disconnect();
      chartsRef.current.forEach((c) => c.remove());
      chartsRef.current = [];
      seriesRef.current = {};
    };
  }, [buildCharts]);

  /* ── update data ─────────────────────────────────────────────── */

  useEffect(() => {
    const s = seriesRef.current;
    if (!s.candles || candles.length === 0) return;

    const hasImpulse = indicators?.impulse_color?.some((v) => v != null);

    // ── Main: Candles ──
    const cd: CandlestickData[] = candles.map((c, i) => {
      const base: CandlestickData = {
        time: toTime(c.timestamp),
        open: c.open, high: c.high, low: c.low, close: c.close,
      };
      if (hasImpulse && indicators?.impulse_color[i]) {
        const ic = indicators.impulse_color[i] as string;
        const m = IMPULSE_MAP[ic];
        if (m) return { ...base, color: m.body, borderColor: m.body, wickColor: m.wick };
      }
      return base;
    });
    s.candles.setData(cd);

    // ── Main: Volume ──
    if (s.volume) {
      const vd: HistogramData[] = candles.map((c, i) => {
        let color = c.close >= c.open ? "#22c55e30" : "#ef444430";
        if (hasImpulse && indicators?.impulse_color[i]) {
          const ic = indicators.impulse_color[i];
          if (ic === "green") color = "#22c55e30";
          else if (ic === "red") color = "#ef444430";
          else color = "#6366f120";
        }
        return { time: toTime(c.timestamp), value: c.volume, color };
      });
      s.volume.setData(vd);
    }

    // Helper to build LineData from an indicator array
    const line = (arr?: (number | null)[]) => {
      if (!arr) return [];
      const out: LineData[] = [];
      for (let i = 0; i < candles.length; i++) {
        if (arr[i] != null) out.push({ time: toTime(candles[i].timestamp), value: arr[i] as number });
      }
      return out;
    };

    // ── Main: EMA + SafeZone overlays ──
    s.ema13?.setData(line(indicators?.ema13));
    s.ema22?.setData(line(indicators?.ema22));
    s.szLong?.setData(line(indicators?.safezone_long));
    s.szShort?.setData(line(indicators?.safezone_short));

    // ── MACD pane ──
    if (s.macdHist && indicators?.macd_histogram) {
      const hd: HistogramData[] = [];
      for (let i = 0; i < candles.length; i++) {
        const val = indicators.macd_histogram[i];
        if (val == null) continue;
        const prev = i > 0 ? indicators.macd_histogram[i - 1] : null;
        const color = val >= 0
          ? (prev != null && val > prev ? "#26A69A" : "#B2DFDB")
          : (prev != null && val > prev ? "#FFCDD2" : "#FF5252");
        hd.push({ time: toTime(candles[i].timestamp), value: val, color });
      }
      s.macdHist.setData(hd);
    }
    s.macdLine?.setData(line(indicators?.macd_line));
    s.macdSignal?.setData(line(indicators?.macd_signal));

    // ── Force Index pane ──
    if (s.fi2 && indicators?.force_index_2) {
      const fd: HistogramData[] = [];
      for (let i = 0; i < candles.length; i++) {
        const val = indicators.force_index_2[i];
        if (val == null) continue;
        fd.push({
          time: toTime(candles[i].timestamp), value: val,
          color: val >= 0 ? "#26a69a80" : "#ef535080",
        });
      }
      s.fi2.setData(fd);
    }
    if (s.fi13) s.fi13.setData(line(indicators?.force_index));

    // ── Elder-Ray pane ──
    if (s.erBull && indicators?.elder_ray_bull) {
      const bd: HistogramData[] = [];
      for (let i = 0; i < candles.length; i++) {
        const val = indicators.elder_ray_bull[i];
        if (val == null) continue;
        bd.push({
          time: toTime(candles[i].timestamp), value: val,
          color: val >= 0 ? "#26a69a" : "#26a69a60",
        });
      }
      s.erBull.setData(bd);
    }
    if (s.erBear && indicators?.elder_ray_bear) {
      const bd: HistogramData[] = [];
      for (let i = 0; i < candles.length; i++) {
        const val = indicators.elder_ray_bear[i];
        if (val == null) continue;
        bd.push({
          time: toTime(candles[i].timestamp), value: val,
          color: val <= 0 ? "#ef5350" : "#ef535060",
        });
      }
      s.erBear.setData(bd);
    }

    // Fit content on the main chart only on full reload (not incremental)
    if (candles.length !== prevCandleCountRef.current) {
      chartsRef.current[0]?.timeScale().fitContent();
    }
    prevCandleCountRef.current = candles.length;
  }, [candles, indicators]);

  /* ── render ──────────────────────────────────────────────────── */

  // Determine FI label
  const fiLabel = indicators?.force_index_2?.some((v) => v != null) && indicators?.force_index?.some((v) => v != null)
    ? "Force Index(2,13)"
    : indicators?.force_index_2?.some((v) => v != null) ? "Force Index(2)" : "Force Index(13)";

  return (
    <div ref={wrapperRef} className="flex flex-col w-full h-full">
      {/* Main price chart — fills remaining space */}
      <div className="relative flex-1 min-h-[120px]">
        {/* Legend */}
        <div className="absolute top-1 left-2 z-10 flex items-center gap-3 text-[9px] font-mono pointer-events-none">
          {indicators?.ema13?.some((v) => v != null) && (
            <span style={{ color: "#f59e0b" }}>EMA(13)</span>
          )}
          {indicators?.ema22?.some((v) => v != null) && (
            <span style={{ color: "#8b5cf6" }}>EMA(22)</span>
          )}
          {indicators?.safezone_long?.some((v) => v != null) && (
            <>
              <span style={{ color: "#22c55e60" }}>SZ-Long</span>
              <span style={{ color: "#ef444460" }}>SZ-Short</span>
            </>
          )}
        </div>
        <div ref={mainRef} className="absolute inset-0" />
      </div>

      {/* MACD pane */}
      {hasMACD && (
        <div className="relative" style={{ height: 100 }}>
          <span className="absolute top-0.5 left-2 z-10 text-[9px] font-mono text-border-light pointer-events-none">
            MACD(12,26,9)
          </span>
          <div ref={macdRef} className="absolute inset-0 border-t border-border" />
        </div>
      )}

      {/* Force Index pane */}
      {hasFI && (
        <div className="relative" style={{ height: 80 }}>
          <span className="absolute top-0.5 left-2 z-10 text-[9px] font-mono text-border-light pointer-events-none">
            {fiLabel}
          </span>
          <div ref={fiRef} className="absolute inset-0 border-t border-border" />
        </div>
      )}

      {/* Elder-Ray pane */}
      {hasER && (
        <div className="relative" style={{ height: 80 }}>
          <span className="absolute top-0.5 left-2 z-10 text-[9px] font-mono text-border-light pointer-events-none">
            Elder-Ray(13){" "}
            <span className="text-[#26a69a]">Bull</span>{" / "}
            <span className="text-[#ef5350]">Bear</span>
          </span>
          <div ref={erRef} className="absolute inset-0 border-t border-border" />
        </div>
      )}
    </div>
  );
}
