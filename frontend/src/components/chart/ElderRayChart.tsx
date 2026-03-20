"use client";

import { useEffect, useRef, useState } from "react";
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
  const [legendBull, setLegendBull] = useState<number | null>(null);
  const [legendBear, setLegendBear] = useState<number | null>(null);

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

    const bullSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "price", precision: 2 },
      priceLineVisible: false, lastValueVisible: false,
    });
    seriesRefs.current.bull = bullSeries;

    const bearSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "price", precision: 2 },
      priceLineVisible: false, lastValueVisible: false,
    });
    seriesRefs.current.bear = bearSeries;

    // Legend on crosshair
    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData) {
        setLegendBull(null);
        setLegendBear(null);
        return;
      }
      const bd = param.seriesData.get(bullSeries) as HistogramData | undefined;
      const brd = param.seriesData.get(bearSeries) as HistogramData | undefined;
      setLegendBull(bd?.value ?? null);
      setLegendBear(brd?.value ?? null);
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
      lastErCountRef.current = 0;
    };
  }, [height, theme]);

  const lastErCountRef = useRef(0);

  useEffect(() => {
    const refs = seriesRefs.current;
    if (!refs.bull || !refs.bear) return;
    if (!timestamps.length) return;
    if (timestamps.length === lastErCountRef.current) return;
    lastErCountRef.current = timestamps.length;
    try {

    const T = "rgba(0,0,0,0)";

    const bullData: HistogramData[] = timestamps.map((ts, i) => {
      const bp = bullPower[i];
      return {
        time: toTime(ts), value: bp ?? 0,
        color: bp == null ? T : bp >= 0 ? "#26a69a" : "#26a69a80",
      };
    });

    const bearData: HistogramData[] = timestamps.map((ts, i) => {
      const brp = bearPower[i];
      return {
        time: toTime(ts), value: brp ?? 0,
        color: brp == null ? T : brp <= 0 ? "#ef5350" : "#ef535080",
      };
    });

    refs.bull.setData(bullData);
    refs.bear.setData(bearData);
    if (!(chartRef.current as any)?.__fitted) {
      chartRef.current?.timeScale().fitContent();
      if (chartRef.current) (chartRef.current as any).__fitted = true;
    }
    } catch { /* setData conflict */ }
  }, [timestamps, bullPower, bearPower, height]);

  if (!bullPower?.some((v) => v != null)) return null;

  // Legend values
  const bull = legendBull ?? bullPower.filter(v => v != null).slice(-1)[0] ?? 0;
  const bear = legendBear ?? bearPower.filter(v => v != null).slice(-1)[0] ?? 0;

  return (
    <div className="relative">
      <div className="absolute top-0.5 left-2 z-10 flex items-center gap-2 text-[9px] font-mono pointer-events-none select-none">
        <span className="text-muted">Elder-Ray(13)</span>
        <span style={{ color: "#26a69a" }}>Bull {bull.toFixed(2)}</span>
        <span style={{ color: "#ef5350" }}>Bear {bear.toFixed(2)}</span>
      </div>
      <div
        ref={containerRef}
        className="w-full border-t border-border overflow-hidden"
        style={{ height }}
      />
    </div>
  );
}
