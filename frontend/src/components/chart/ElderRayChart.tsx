"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  HistogramSeries,
  type IChartApi,
  ColorType,
  type HistogramData,
  type Time,
} from "lightweight-charts";
import { useTheme } from "@/hooks/useTheme";
import { getChartTheme } from "@/lib/chartTheme";

interface ElderRayChartProps {
  timestamps: string[];
  bullPower: (number | null)[];
  bearPower: (number | null)[];
  height?: number;
}

function toTime(ts: string): Time {
  return (new Date(ts).getTime() / 1000) as Time;
}

export default function ElderRayChart({
  timestamps,
  bullPower,
  bearPower,
  height = 90,
}: ElderRayChartProps) {
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

    // Bull Power (green histogram)
    const bullSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "price", precision: 2 },
      priceLineVisible: false,
      lastValueVisible: false,
    });
    seriesRefs.current.bull = bullSeries;

    // Bear Power (red histogram)
    const bearSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "price", precision: 2 },
      priceLineVisible: false,
      lastValueVisible: false,
    });
    seriesRefs.current.bear = bearSeries;

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
  }, [height, theme]);

  // Update data
  useEffect(() => {
    const refs = seriesRefs.current;
    if (!refs.bull || !refs.bear) return;
    if (!timestamps.length) return;

    const bullData: HistogramData[] = [];
    const bearData: HistogramData[] = [];

    for (let i = 0; i < timestamps.length; i++) {
      const time = toTime(timestamps[i]);
      const bp = bullPower[i];
      const brp = bearPower[i];

      if (bp != null) {
        bullData.push({
          time,
          value: bp,
          color: bp >= 0 ? "#26a69a" : "#26a69a80",
        });
      }

      if (brp != null) {
        bearData.push({
          time,
          value: brp,
          color: brp <= 0 ? "#ef5350" : "#ef535080",
        });
      }
    }

    refs.bull.setData(bullData);
    refs.bear.setData(bearData);
    chartRef.current?.timeScale().fitContent();
  }, [timestamps, bullPower, bearPower, height]);

  if (!bullPower?.some((v) => v != null)) return null;

  return (
    <div className="relative">
      <span className="absolute top-0.5 left-2 z-10 text-[9px] text-muted font-mono">
        Elder-Ray(13) &nbsp;
        <span className="text-[#26a69a]">Bull</span> / <span className="text-[#ef5350]">Bear</span>
      </span>
      <div
        ref={containerRef}
        className="w-full border-t border-border overflow-hidden"
        style={{ height }}
      />
    </div>
  );
}
