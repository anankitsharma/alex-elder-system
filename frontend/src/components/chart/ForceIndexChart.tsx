"use client";

import { useEffect, useRef } from "react";
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

    // FI-2 as histogram (more prominent, used for entry timing)
    if (forceIndex2) {
      const fi2Series = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "price", precision: 0 },
        priceLineVisible: false,
        lastValueVisible: false,
      });
      seriesRefs.current.fi2 = fi2Series;
    }

    // FI-13 as line (trend confirmation)
    if (forceIndex13) {
      const fi13Series = chart.addSeries(LineSeries, {
        color: "#f59e0b",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      seriesRefs.current.fi13 = fi13Series;
    }

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
  }, [height, !!forceIndex2, !!forceIndex13, theme]);

  useEffect(() => {
    const refs = seriesRefs.current;
    if (!timestamps.length) return;

    // FI-2 histogram
    if (refs.fi2 && forceIndex2) {
      const data: HistogramData[] = [];
      for (let i = 0; i < timestamps.length; i++) {
        const val = forceIndex2[i];
        if (val != null) {
          data.push({
            time: toTime(timestamps[i]),
            value: val,
            color: val >= 0 ? "#26a69a80" : "#ef535080",
          });
        }
      }
      refs.fi2.setData(data);
    }

    // FI-13 line
    if (refs.fi13 && forceIndex13) {
      const data: LineData[] = [];
      for (let i = 0; i < timestamps.length; i++) {
        if (forceIndex13[i] != null) {
          data.push({
            time: toTime(timestamps[i]),
            value: forceIndex13[i] as number,
          });
        }
      }
      refs.fi13.setData(data);
    }

    chartRef.current?.timeScale().fitContent();
  }, [timestamps, forceIndex2, forceIndex13, height]);

  const hasData = forceIndex2?.some((v) => v != null) || forceIndex13?.some((v) => v != null);
  if (!hasData) return null;

  const label = forceIndex2 && forceIndex13
    ? "Force Index(2,13)"
    : forceIndex2
    ? "Force Index(2)"
    : "Force Index(13)";

  return (
    <div className="relative">
      <span className="absolute top-0.5 left-2 z-10 text-[9px] text-muted font-mono">
        {label}
      </span>
      <div
        ref={containerRef}
        className="w-full border-t border-border overflow-hidden"
        style={{ height }}
      />
    </div>
  );
}
