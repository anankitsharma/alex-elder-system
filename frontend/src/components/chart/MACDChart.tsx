"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  ColorType,
  type HistogramData,
  type LineData,
  type Time,
} from "lightweight-charts";
import type { CandleData, IndicatorData } from "@/lib/api";
import { useTheme } from "@/hooks/useTheme";
import { getChartTheme } from "@/lib/chartTheme";

interface MACDChartProps {
  candles: CandleData[];
  indicators: IndicatorData | null;
  height?: number;
}

interface MACDLegend { macd: number; signal: number; hist: number; }

function toTime(ts: string): Time {
  return (new Date(ts).getTime() / 1000) as Time;
}

export function MACDChart({ candles, indicators, height = 120 }: MACDChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRefs = useRef<Record<string, any>>({});
  const { theme } = useTheme();
  const [legend, setLegend] = useState<MACDLegend | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const ct = getChartTheme();

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: ct.bg },
        textColor: ct.text,
        fontSize: 10,
      },
      grid: {
        vertLines: { color: ct.grid },
        horzLines: { color: ct.grid },
      },
      crosshair: {
        vertLine: { visible: false },
        horzLine: { visible: false },
      },
      rightPriceScale: {
        borderColor: ct.border,
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: ct.border,
        visible: false,
      },
    });

    const histSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "price", precision: 2 },
      priceLineVisible: false, lastValueVisible: false,
    });
    seriesRefs.current.histogram = histSeries;

    const macdLineSeries = chart.addSeries(LineSeries, {
      color: "#3b82f6", lineWidth: 1,
      priceLineVisible: false, lastValueVisible: false,
    });
    seriesRefs.current.macdLine = macdLineSeries;

    const signalSeries = chart.addSeries(LineSeries, {
      color: "#f97316", lineWidth: 1,
      priceLineVisible: false, lastValueVisible: false,
    });
    seriesRefs.current.signal = signalSeries;

    // Legend on crosshair
    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData) { setLegend(null); return; }
      const hd = param.seriesData.get(histSeries) as HistogramData | undefined;
      const md = param.seriesData.get(macdLineSeries) as { value?: number } | undefined;
      const sd = param.seriesData.get(signalSeries) as { value?: number } | undefined;
      if (hd || md || sd) {
        setLegend({
          hist: hd?.value ?? 0,
          macd: (md as any)?.value ?? 0,
          signal: (sd as any)?.value ?? 0,
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
  }, [height, theme]);

  const lastMacdCountRef = useRef(0);

  useEffect(() => {
    const refs = seriesRefs.current;
    if (!refs.histogram || !indicators || candles.length === 0) return;
    if (candles.length === lastMacdCountRef.current) return;
    try {
    lastMacdCountRef.current = candles.length;

    const T = "rgba(0,0,0,0)";
    const histData: HistogramData[] = candles.map((c, i) => {
      const val = indicators.macd_histogram[i];
      const time = toTime(c.timestamp);
      if (val == null) return { time, value: 0, color: T };
      const prev = i > 0 ? indicators.macd_histogram[i - 1] : null;
      let color: string;
      if (val >= 0) {
        color = prev != null && val > prev ? "#26A69A" : "#B2DFDB";
      } else {
        color = prev != null && val > prev ? "#FFCDD2" : "#FF5252";
      }
      return { time, value: val, color };
    });
    refs.histogram.setData(histData);

    const macdData: LineData[] = candles.map((c, i) => ({
      time: toTime(c.timestamp), value: (indicators.macd_line[i] ?? 0) as number,
    }));
    refs.macdLine.setData(macdData);

    const sigData: LineData[] = candles.map((c, i) => ({
      time: toTime(c.timestamp), value: (indicators.macd_signal[i] ?? 0) as number,
    }));
    refs.signal.setData(sigData);

    // fitContent only once after initial data load
    if (!(chartRef.current as any)?.__fitted) {
      chartRef.current?.timeScale().fitContent();
      if (chartRef.current) (chartRef.current as any).__fitted = true;
    }
    } catch { /* setData conflict — safe to ignore */ }
  }, [candles, indicators, height]);

  if (!indicators?.macd_histogram?.some((v) => v != null)) return null;

  // Legend values
  const d = legend ?? (() => {
    const lastIdx = indicators.macd_histogram.length - 1;
    return {
      hist: indicators.macd_histogram[lastIdx] ?? 0,
      macd: indicators.macd_line?.[lastIdx] ?? 0,
      signal: indicators.macd_signal?.[lastIdx] ?? 0,
    };
  })();

  return (
    <div className="relative">
      <div className="absolute top-0.5 left-2 z-10 flex items-center gap-2 text-[9px] font-mono pointer-events-none select-none">
        <span className="text-muted">MACD(12,26,9)</span>
        <span style={{ color: "#3b82f6" }}>{d.macd.toFixed(2)}</span>
        <span style={{ color: "#f97316" }}>{d.signal.toFixed(2)}</span>
        <span style={{ color: d.hist >= 0 ? "#26A69A" : "#FF5252" }}>{d.hist.toFixed(2)}</span>
      </div>
      <div
        ref={containerRef}
        className="w-full border-t border-border overflow-hidden"
        style={{ height }}
      />
    </div>
  );
}
