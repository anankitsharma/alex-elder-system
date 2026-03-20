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

import { useEffect, useRef, useCallback, useState } from "react";
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

/* ── OHLCV Legend data ─────────────────────────────────────────── */
interface OHLCVData {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  change: number;
  changePct: number;
}

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
  const [ohlcv, setOhlcv] = useState<OHLCVData | null>(null);

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
              vertLine: { color: crossColor, width: 1, style: 2, labelVisible: true },
              horzLine: { color: crossColor, width: 1, style: 2 },
            }
          : {
              mode: CrosshairMode.Normal,
              vertLine: { color: crossColor, width: 1, style: 2, labelVisible: true },
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
          rightOffset: 20,               // Empty space on right (like TradingView)
        },
      });

      if (isMain) {
        const cs = chart.addSeries(CandlestickSeries, {
          upColor: "#22c55e", downColor: "#ef4444",
          borderUpColor: "#22c55e", borderDownColor: "#ef4444",
          wickUpColor: "#22c55e88", wickDownColor: "#ef444488",
          lastValueVisible: false,  // Hide the default colored price label
          priceLineVisible: false,  // Hide the default price line
        });
        seriesRef.current.candles = cs;

        if (showVolume) {
          const vol = chart.addSeries(HistogramSeries, {
            priceFormat: { type: "volume" },
            priceScaleId: "vol",
            lastValueVisible: false,
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

    // Sync visible range using TIME-BASED range (not logical index).
    // This ensures alignment even when charts have different data lengths.
    charts.forEach((chart, idx) => {
      chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
        if (syncingRef.current) return;
        syncingRef.current = true;
        try {
          const timeRange = chart.timeScale().getVisibleRange();
          if (timeRange) {
            charts.forEach((other, oidx) => {
              if (oidx !== idx) {
                try { other.timeScale().setVisibleRange(timeRange); } catch { /* ok */ }
              }
            });
          }
        } catch { /* ok */ }
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

    // OHLCV legend: track crosshair on main chart to show inline data
    const mainChart2 = charts[0];
    if (mainChart2 && seriesRef.current.candles) {
      const candleSeries = seriesRef.current.candles;
      const volSeries = seriesRef.current.volume;
      mainChart2.subscribeCrosshairMove((param) => {
        if (!param.time || !param.seriesData) {
          // Reset to last candle data when cursor leaves
          setOhlcv(null);
          return;
        }
        const cd = param.seriesData.get(candleSeries) as CandlestickData | undefined;
        const vd = volSeries ? param.seriesData.get(volSeries) as HistogramData | undefined : undefined;
        if (cd) {
          const change = cd.close - cd.open;
          const changePct = cd.open !== 0 ? (change / cd.open) * 100 : 0;
          setOhlcv({
            open: cd.open, high: cd.high, low: cd.low, close: cd.close,
            volume: vd?.value ?? 0,
            change, changePct,
          });
        }
      });
    }

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

  /* ── data update (candles + indicators in one effect) ─────── */

  useEffect(() => {
    const s = seriesRef.current;
    if (!s.candles || candles.length === 0) return;

    try {

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

    // Only fitContent + sync on INITIAL load (candle count 0→N) or symbol change.
    const isInitialLoad = prevCandleCountRef.current === 0 && candles.length > 0;
    const isSymbolChange = candles.length > 0 && candles.length !== prevCandleCountRef.current
      && Math.abs(candles.length - prevCandleCountRef.current) > 5;

    if (isInitialLoad || isSymbolChange) {
      const mainChart = chartsRef.current[0];
      if (mainChart) {
        syncingRef.current = true;
        mainChart.timeScale().fitContent();
        const doSync = () => {
          try {
            const range = mainChart.timeScale().getVisibleRange();
            if (range) {
              chartsRef.current.forEach((c, idx) => {
                if (idx > 0) {
                  try { c.timeScale().setVisibleRange(range); } catch { /* ok */ }
                }
              });
            }
          } catch { /* disposed */ }
        };
        setTimeout(doSync, 50);
        setTimeout(() => { doSync(); syncingRef.current = false; }, 200);
      }
    }
    prevCandleCountRef.current = candles.length;

    // ── Indicator overlays + sub-charts ──
    const indTs = indicators?.timestamps ?? [];
    const indLen = indTs.length;

    // Overlays on main chart use candle timestamps (same chart instance)
    const overlayLine = (arr?: (number | null)[]) => {
      if (!arr) return [];
      const out: LineData[] = [];
      for (let i = 0; i < candles.length && i < arr.length; i++) {
        if (arr[i] != null) {
          out.push({ time: toTime(candles[i].timestamp), value: arr[i] as number });
        }
      }
      return out;
    };

    s.ema13?.setData(overlayLine(indicators?.ema13));
    s.ema22?.setData(overlayLine(indicators?.ema22));
    s.szLong?.setData(overlayLine(indicators?.safezone_long));
    s.szShort?.setData(overlayLine(indicators?.safezone_short));

    // Sub-chart line builder — uses indicator timestamps, skips nulls
    const indLine = (arr?: (number | null)[]) => {
      if (!arr) return [];
      const out: LineData[] = [];
      for (let i = 0; i < indLen && i < arr.length; i++) {
        if (arr[i] != null) {
          out.push({ time: toTime(indTs[i]), value: arr[i] as number });
        }
      }
      return out;
    };

    // Sub-chart histogram builder — uses indicator timestamps, skips nulls
    const indHist = (arr: (number | null)[], colorFn: (val: number, i: number) => string) => {
      const out: HistogramData[] = [];
      for (let i = 0; i < indLen && i < arr.length; i++) {
        if (arr[i] != null) {
          out.push({ time: toTime(indTs[i]), value: arr[i] as number, color: colorFn(arr[i] as number, i) });
        }
      }
      return out;
    };

    // MACD pane
    if (s.macdHist && indicators?.macd_histogram) {
      s.macdHist.setData(indHist(indicators.macd_histogram, (val, i) => {
        const prev = i > 0 ? indicators!.macd_histogram[i - 1] : null;
        return val >= 0
          ? (prev != null && val > prev ? "#26A69A" : "#B2DFDB")
          : (prev != null && val > prev ? "#FFCDD2" : "#FF5252");
      }));
    }
    s.macdLine?.setData(indLine(indicators?.macd_line));
    s.macdSignal?.setData(indLine(indicators?.macd_signal));

    // Force Index pane
    if (s.fi2 && indicators?.force_index_2) {
      s.fi2.setData(indHist(indicators.force_index_2, (val) =>
        val >= 0 ? "#26a69a80" : "#ef535080"
      ));
    }
    if (s.fi13) s.fi13.setData(indLine(indicators?.force_index));

    // Elder-Ray pane
    if (s.erBull && indicators?.elder_ray_bull) {
      s.erBull.setData(indHist(indicators.elder_ray_bull, (val) =>
        val >= 0 ? "#26a69a" : "#26a69a60"
      ));
    }
    if (s.erBear && indicators?.elder_ray_bear) {
      s.erBear.setData(indHist(indicators.elder_ray_bear, (val) =>
        val <= 0 ? "#ef5350" : "#ef535060"
      ));
    }

    } catch { /* setData/update conflict — safe to skip */ }
  }, [candles, indicators]);

  /* ── running bar — incremental update via series.update() ───── */

  const runningBar = useTradingStore((s) => s.runningBar);

  useEffect(() => {
    const s = seriesRef.current;
    if (!s.candles || !runningBar) return;

    const time = toTime(runningBar.timestamp);

    // Update candle — same timestamp = in-place update, new timestamp = append
    try {
      s.candles.update({
        time,
        open: runningBar.open,
        high: runningBar.high,
        low: runningBar.low,
        close: runningBar.close,
        borderColor: runningBar.close >= runningBar.open ? "#22c55ecc" : "#ef4444cc",
      } as CandlestickData);

      if (s.volume) {
        s.volume.update({
          time,
          value: runningBar.volume,
          color: runningBar.close >= runningBar.open ? "#22c55e30" : "#ef444430",
        } as HistogramData);
      }

      updatePriceLine(s.candles, runningBar.close);
    } catch { /* running bar update conflict — next tick will retry */ }
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

  // Compute display OHLCV — use crosshair data or fall back to last candle
  const displayOhlcv: OHLCVData | null = ohlcv ?? (candles.length > 0 ? (() => {
    const last = candles[candles.length - 1];
    const change = last.close - last.open;
    return {
      open: last.open, high: last.high, low: last.low, close: last.close,
      volume: last.volume, change, changePct: last.open !== 0 ? (change / last.open) * 100 : 0,
    };
  })() : null);

  const isUp = displayOhlcv ? displayOhlcv.close >= displayOhlcv.open : true;
  const ohlcColor = isUp ? "#22c55e" : "#ef4444";

  // Format numbers compactly
  const fmt = (n: number) => {
    if (n >= 1e7) return (n / 1e7).toFixed(2) + "Cr";
    if (n >= 1e5) return (n / 1e5).toFixed(2) + "L";
    if (n >= 1000) return (n / 1000).toFixed(1) + "K";
    return n.toFixed(2);
  };
  const fmtP = (n: number) => n.toFixed(2);

  return (
    <div ref={wrapperRef} className="flex flex-col w-full h-full">
      <div className="relative flex-1 min-h-[120px]">
        {/* TradingView-style inline OHLCV legend */}
        <div className="absolute top-1 left-2 z-10 flex items-center gap-2 text-[10px] font-mono pointer-events-none select-none">
          {displayOhlcv && (
            <>
              <span className="text-muted">O</span>
              <span style={{ color: ohlcColor }}>{fmtP(displayOhlcv.open)}</span>
              <span className="text-muted">H</span>
              <span style={{ color: ohlcColor }}>{fmtP(displayOhlcv.high)}</span>
              <span className="text-muted">L</span>
              <span style={{ color: ohlcColor }}>{fmtP(displayOhlcv.low)}</span>
              <span className="text-muted">C</span>
              <span style={{ color: ohlcColor }}>{fmtP(displayOhlcv.close)}</span>
              <span style={{ color: ohlcColor, fontSize: "9px" }}>
                {displayOhlcv.change >= 0 ? "+" : ""}{fmtP(displayOhlcv.change)} ({displayOhlcv.changePct >= 0 ? "+" : ""}{displayOhlcv.changePct.toFixed(2)}%)
              </span>
              {displayOhlcv.volume > 0 && (
                <>
                  <span className="text-muted ml-1">Vol</span>
                  <span className="text-muted">{fmt(displayOhlcv.volume)}</span>
                </>
              )}
            </>
          )}
          <span className="text-muted">│</span>
          {indicators?.ema13?.some((v) => v != null) && (
            <span style={{ color: "#f59e0b" }}>EMA(13)</span>
          )}
          {indicators?.ema22?.some((v) => v != null) && (
            <span style={{ color: "#8b5cf6" }}>EMA(22)</span>
          )}
          {indicators?.safezone_long?.some((v) => v != null) && (
            <>
              <span style={{ color: "#22c55e60" }}>SZ↑</span>
              <span style={{ color: "#ef444460" }}>SZ↓</span>
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
