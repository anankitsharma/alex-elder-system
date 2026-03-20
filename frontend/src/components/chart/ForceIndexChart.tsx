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
import { useTheme } from "@/hooks/useTheme";
import { getChartTheme } from "@/lib/chartTheme";

interface ForceIndexChartProps {
  timestamps: string[];
  forceIndex13?: (number | null)[];
  forceIndex2?: (number | null)[];
  height?: number;
}

function toTime(ts: string): Time {
  return (new Date(ts).getTime() / 1000) as Time;
}

const fmtFI = (n: number) => {
  const abs = Math.abs(n);
  const s = n < 0 ? "-" : "";
  if (abs >= 1e7) return s + (abs / 1e7).toFixed(1) + "Cr";
  if (abs >= 1e5) return s + (abs / 1e5).toFixed(1) + "L";
  if (abs >= 1000) return s + (abs / 1000).toFixed(0) + "K";
  return n.toFixed(0);
};

export default function ForceIndexChart({
  timestamps,
  forceIndex13,
  forceIndex2,
  height = 90,
}: ForceIndexChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRefs = useRef<Record<string, any>>({});
  const { theme } = useTheme();
  const [legendFI2, setLegendFI2] = useState<number | null>(null);
  const [legendFI13, setLegendFI13] = useState<number | null>(null);

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

    if (forceIndex2) {
      const fi2Series = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "price", precision: 0 },
        priceLineVisible: false, lastValueVisible: false,
      });
      seriesRefs.current.fi2 = fi2Series;
    }

    if (forceIndex13) {
      const fi13Series = chart.addSeries(LineSeries, {
        color: "#f59e0b", lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false,
      });
      seriesRefs.current.fi13 = fi13Series;
    }

    // Legend on crosshair
    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData) {
        setLegendFI2(null);
        setLegendFI13(null);
        return;
      }
      if (seriesRefs.current.fi2) {
        const d = param.seriesData.get(seriesRefs.current.fi2) as HistogramData | undefined;
        setLegendFI2(d?.value ?? null);
      }
      if (seriesRefs.current.fi13) {
        const d = param.seriesData.get(seriesRefs.current.fi13) as { value?: number } | undefined;
        setLegendFI13((d as any)?.value ?? null);
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
  }, [height, !!forceIndex2, !!forceIndex13, theme]);

  const lastFiCountRef = useRef(0);

  useEffect(() => {
    const refs = seriesRefs.current;
    if (!timestamps.length) return;
    if (timestamps.length === lastFiCountRef.current) return;
    lastFiCountRef.current = timestamps.length;
    try {

    const T = "rgba(0,0,0,0)";

    if (refs.fi2 && forceIndex2) {
      const data: HistogramData[] = timestamps.map((ts, i) => {
        const val = forceIndex2[i];
        return {
          time: toTime(ts), value: val ?? 0,
          color: val == null ? T : val >= 0 ? "#26a69a80" : "#ef535080",
        };
      });
      refs.fi2.setData(data);
    }

    if (refs.fi13 && forceIndex13) {
      const data: LineData[] = timestamps.map((ts, i) => ({
        time: toTime(ts), value: (forceIndex13[i] ?? 0) as number,
      }));
      refs.fi13.setData(data);
    }

    if (!(chartRef.current as any)?.__fitted) {
      chartRef.current?.timeScale().fitContent();
      if (chartRef.current) (chartRef.current as any).__fitted = true;
    }
    } catch { /* setData conflict */ }
  }, [timestamps, forceIndex2, forceIndex13, height]);

  const hasData = forceIndex2?.some((v) => v != null) || forceIndex13?.some((v) => v != null);
  if (!hasData) return null;

  const label = forceIndex2 && forceIndex13 ? "FI(2,13)" : forceIndex2 ? "FI(2)" : "FI(13)";

  // Display values — crosshair or last
  const lastFI2 = legendFI2 ?? (forceIndex2 ? forceIndex2.filter(v => v != null).slice(-1)[0] ?? 0 : null);
  const lastFI13 = legendFI13 ?? (forceIndex13 ? forceIndex13.filter(v => v != null).slice(-1)[0] ?? 0 : null);

  return (
    <div className="relative">
      <div className="absolute top-0.5 left-2 z-10 flex items-center gap-2 text-[9px] font-mono pointer-events-none select-none">
        <span className="text-muted">{label}</span>
        {lastFI2 != null && (
          <span style={{ color: lastFI2 >= 0 ? "#26a69a" : "#ef5350" }}>{fmtFI(lastFI2)}</span>
        )}
        {lastFI13 != null && (
          <span style={{ color: "#f59e0b" }}>{fmtFI(lastFI13)}</span>
        )}
      </div>
      <div
        ref={containerRef}
        className="w-full border-t border-border overflow-hidden"
        style={{ height }}
      />
    </div>
  );
}
