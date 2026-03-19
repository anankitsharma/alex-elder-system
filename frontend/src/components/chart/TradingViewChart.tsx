"use client";

/**
 * TradingView-style multi-pane chart with live incremental updates.
 *
 * Layout (top to bottom):
 *   Main pane — Candlesticks + Volume + EMA + SafeZone + Impulse coloring
 *   MACD pane — Histogram (4-color) + MACD line + Signal line
 *   Force Index pane — FI-2 histogram + FI-13 line
 *   Elder-Ray pane — Bull Power + Bear Power histograms
 *
 * All panes share the same time axis (synced scroll/zoom/crosshair).
 * Uses series.update() for running bars — O(1) instead of O(N) setData().
 */

import { useEffect, useRef, useCallback } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  ColorType,
  CrosshairMode,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type Time,
  type LogicalRange,
  LineStyle,
  type IPriceLine,
} from "lightweight-charts";
import type { CandleData, IndicatorData } from "@/lib/api";
import { useTheme } from "@/hooks/useTheme";
import { getChartTheme } from "@/lib/chartTheme";
import { useTradingStore } from "@/store/useTradingStore";

/* ── props ──────────────────────────────────────────────────────── */

interface TradingViewChartProps {
  candles: CandleData[];
  indicators?: IndicatorData | null;
  showVolume?: boolean;
  showMACD?: boolean;
  showForceIndex?: boolean;
  showElderRay?: boolean;
}

/* ── constants ──────────────────────────────────────────────────── */

const IMPULSE_MAP: Record<string, { body: string; wick: string }> = {
  green:  { body: "#22c55e", wick: "#22c55e88" },
  red:    { body: "#ef4444", wick: "#ef444488" },
  blue:   { body: "#6366f1", wick: "#6366f188" },
};

// Running bar has slightly transparent colors to distinguish from completed bars
const RUNNING_IMPULSE_MAP: Record<string, { body: string; wick: string }> = {
  green:  { body: "#22c55ea0", wick: "#22c55e60" },
  red:    { body: "#ef4444a0", wick: "#ef444460" },
  blue:   { body: "#6366f1a0", wick: "#6366f160" },
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

  const mainRef = useRef<HTMLDivElement>(null);
  const macdRef = useRef<HTMLDivElement>(null);
  const fiRef   = useRef<HTMLDivElement>(null);
  const erRef   = useRef<HTMLDivElement>(null);

  const chartsRef = useRef<IChartApi[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef = useRef<Record<string, any>>({});
  const syncingRef = useRef(false);
  const prevCandleCountRef = useRef(0);
  const priceLineRef = useRef<IPriceLine | null>(null);
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
    chartsRef.current.forEach((c) => c.remove());
    chartsRef.current = [];
    seriesRef.current = {};
    priceLineRef.current = null;

    const containerWidth = wrapperRef.current?.clientWidth ?? 800;
    const ct = getChartTheme();

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

      if (isMain) {
        const cs = chart.addSeries(CandlestickSeries, {
          upColor: "#22c55e", downColor: "#ef4444",
          borderUpColor: "#22c55e", borderDownColor: "#ef4444",
          wickUpColor: "#22c55e88", wickDownColor: "#ef444488",
        });
        seriesRef.current.candles = cs;

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

        seriesRef.current.ema13 = chart.addSeries(LineSeries, {
          color: "#f59e0b", lineWidth: 1,
          priceLineVisible: false, lastValueVisible: false,
        });
        seriesRef.current.ema22 = chart.addSeries(LineSeries, {
          color: "#8b5cf6", lineWidth: 1,
          priceLineVisible: false, lastValueVisible: false,
        });
        seriesRef.current.szLong = chart.addSeries(LineSeries, {
          color: "#22c55e50", lineWidth: 1, lineStyle: LineStyle.Dashed,
          priceLineVisible: false, lastValueVisible: false,
        });
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

    // Sync visible range
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

    // Sync crosshair
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
      priceLineRef.current = null;
    };
  }, [buildCharts]);

  /* ── full data load (initial + symbol/interval change) ─────── */

  useEffect(() => {
    const s = seriesRef.current;
    if (!s.candles || candles.length === 0) return;

    const hasImpulse = indicators?.impulse_color?.some((v) => v != null);

    // Main: Candles
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

    // Main: Volume
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

    // IMPORTANT: All sub-chart series must include data points for EVERY
    // candle timestamp (even nulls → value 0, transparent). This ensures
    // sub-charts have the same number of logical indices as the main chart,
    // so scroll/zoom sync via setVisibleLogicalRange stays aligned.
    const TRANSPARENT = "rgba(0,0,0,0)";

    const line = (arr?: (number | null)[]) => {
      if (!arr) return [];
      const out: LineData[] = [];
      for (let i = 0; i < candles.length; i++) {
        out.push({
          time: toTime(candles[i].timestamp),
          value: arr[i] != null ? (arr[i] as number) : 0,
        });
      }
      return out;
    };

    s.ema13?.setData(line(indicators?.ema13));
    s.ema22?.setData(line(indicators?.ema22));
    s.szLong?.setData(line(indicators?.safezone_long));
    s.szShort?.setData(line(indicators?.safezone_short));

    // MACD pane — all timestamps included, null → 0 with transparent color
    if (s.macdHist && indicators?.macd_histogram) {
      const hd: HistogramData[] = [];
      for (let i = 0; i < candles.length; i++) {
        const val = indicators.macd_histogram[i];
        const time = toTime(candles[i].timestamp);
        if (val == null) {
          hd.push({ time, value: 0, color: TRANSPARENT });
          continue;
        }
        const prev = i > 0 ? indicators.macd_histogram[i - 1] : null;
        const color = val >= 0
          ? (prev != null && val > prev ? "#26A69A" : "#B2DFDB")
          : (prev != null && val > prev ? "#FFCDD2" : "#FF5252");
        hd.push({ time, value: val, color });
      }
      s.macdHist.setData(hd);
    }
    s.macdLine?.setData(line(indicators?.macd_line));
    s.macdSignal?.setData(line(indicators?.macd_signal));

    // Force Index pane
    if (s.fi2 && indicators?.force_index_2) {
      const fd: HistogramData[] = [];
      for (let i = 0; i < candles.length; i++) {
        const val = indicators.force_index_2[i];
        const time = toTime(candles[i].timestamp);
        if (val == null) {
          fd.push({ time, value: 0, color: TRANSPARENT });
          continue;
        }
        fd.push({ time, value: val, color: val >= 0 ? "#26a69a80" : "#ef535080" });
      }
      s.fi2.setData(fd);
    }
    if (s.fi13) s.fi13.setData(line(indicators?.force_index));

    // Elder-Ray pane
    if (s.erBull && indicators?.elder_ray_bull) {
      const bd: HistogramData[] = [];
      for (let i = 0; i < candles.length; i++) {
        const val = indicators.elder_ray_bull[i];
        const time = toTime(candles[i].timestamp);
        if (val == null) {
          bd.push({ time, value: 0, color: TRANSPARENT });
          continue;
        }
        bd.push({ time, value: val, color: val >= 0 ? "#26a69a" : "#26a69a60" });
      }
      s.erBull.setData(bd);
    }
    if (s.erBear && indicators?.elder_ray_bear) {
      const bd: HistogramData[] = [];
      for (let i = 0; i < candles.length; i++) {
        const val = indicators.elder_ray_bear[i];
        const time = toTime(candles[i].timestamp);
        if (val == null) {
          bd.push({ time, value: 0, color: TRANSPARENT });
          continue;
        }
        bd.push({ time, value: val, color: val <= 0 ? "#ef5350" : "#ef535060" });
      }
      s.erBear.setData(bd);
    }

    // Sync all panes to the main chart's visible range.
    // 1. fitContent on main chart first to establish the canonical range
    // 2. Temporarily disable scroll sync to prevent cascading
    // 3. Force all sub-charts to the exact same logical range
    const mainChart = chartsRef.current[0];
    if (mainChart) {
      mainChart.timeScale().fitContent();
      // Use setTimeout to let the main chart settle its layout, then force-sync
      setTimeout(() => {
        try {
          const range = mainChart.timeScale().getVisibleLogicalRange();
          if (range) {
            syncingRef.current = true;
            chartsRef.current.forEach((c, idx) => {
              if (idx > 0) {
                try { c.timeScale().setVisibleLogicalRange(range); } catch { /* disposed */ }
              }
            });
            syncingRef.current = false;
          }
        } catch { /* disposed */ }
      }, 50);
    }
    prevCandleCountRef.current = candles.length;
  }, [candles, indicators]);

  /* ── running bar — incremental update via series.update() ───── */

  const runningBar = useTradingStore((s) => s.runningBar);

  useEffect(() => {
    const s = seriesRef.current;
    if (!s.candles || !runningBar) return;

    const time = toTime(runningBar.timestamp);

    // Update candle — same timestamp = in-place update, new timestamp = append
    s.candles.update({
      time,
      open: runningBar.open,
      high: runningBar.high,
      low: runningBar.low,
      close: runningBar.close,
      // Slightly different border to indicate running bar
      borderColor: runningBar.close >= runningBar.open ? "#22c55ecc" : "#ef4444cc",
    } as CandlestickData);

    // Update volume running bar
    if (s.volume) {
      s.volume.update({
        time,
        value: runningBar.volume,
        color: runningBar.close >= runningBar.open ? "#22c55e30" : "#ef444430",
      } as HistogramData);
    }

    // Update LTP price line
    updatePriceLine(s.candles, runningBar.close);
  }, [runningBar]);

  /** Create/update a horizontal dashed line showing last traded price */
  function updatePriceLine(
    series: ISeriesApi<"Candlestick">,
    price: number,
  ) {
    try {
      if (priceLineRef.current) {
        series.removePriceLine(priceLineRef.current);
      }
      priceLineRef.current = series.createPriceLine({
        price,
        color: "#2962FF",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "LTP",
      });
    } catch {
      // series may be disposed
    }
  }

  /* ── render ──────────────────────────────────────────────────── */

  const fiLabel = indicators?.force_index_2?.some((v) => v != null) && indicators?.force_index?.some((v) => v != null)
    ? "Force Index(2,13)"
    : indicators?.force_index_2?.some((v) => v != null) ? "Force Index(2)" : "Force Index(13)";

  return (
    <div ref={wrapperRef} className="flex flex-col w-full h-full">
      <div className="relative flex-1 min-h-[120px]">
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

      {hasMACD && (
        <div className="relative" style={{ height: 100 }}>
          <span className="absolute top-0.5 left-2 z-10 text-[9px] font-mono text-border-light pointer-events-none">
            MACD(12,26,9)
          </span>
          <div ref={macdRef} className="absolute inset-0 border-t border-border" />
        </div>
      )}

      {hasFI && (
        <div className="relative" style={{ height: 80 }}>
          <span className="absolute top-0.5 left-2 z-10 text-[9px] font-mono text-border-light pointer-events-none">
            {fiLabel}
          </span>
          <div ref={fiRef} className="absolute inset-0 border-t border-border" />
        </div>
      )}

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
