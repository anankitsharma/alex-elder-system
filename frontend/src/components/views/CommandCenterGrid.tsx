"use client";

import type { CommandCenterAsset } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

interface Props {
  assets: CommandCenterAsset[];
  onSelectAsset: (symbol: string, exchange: string) => void;
}

const GRADE_COLORS: Record<string, string> = {
  A: "bg-green-500/20 text-green-400",
  B: "bg-green-500/10 text-green-400",
  C: "bg-amber-500/10 text-amber-400",
  D: "bg-red-500/10 text-red-400",
};

const TIDE_COLORS: Record<string, string> = {
  BULLISH: "text-green-400",
  BEARISH: "text-red-400",
  NEUTRAL: "text-muted",
};

export default function CommandCenterGrid({ assets, onSelectAsset }: Props) {
  if (assets.length === 0) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-muted text-sm">
        <Loader2 className="w-4 h-4 animate-spin" />
        Waiting for pipeline data...
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-border text-muted">
            <th className="text-left py-1.5 px-2 font-medium">Symbol</th>
            <th className="text-right py-1.5 px-2 font-medium">LTP</th>
            <th className="text-right py-1.5 px-2 font-medium">Chg%</th>
            <th className="text-center py-1.5 px-2 font-medium">Tide</th>
            <th className="text-center py-1.5 px-2 font-medium">Impulse</th>
            <th className="text-center py-1.5 px-2 font-medium">Signal</th>
            <th className="text-center py-1.5 px-2 font-medium">Grade</th>
            <th className="text-right py-1.5 px-2 font-medium">Conf</th>
            <th className="text-right py-1.5 px-2 font-medium">Entry</th>
            <th className="text-right py-1.5 px-2 font-medium">Stop</th>
          </tr>
        </thead>
        <tbody>
          {assets.map((a) => {
            const isUp = (a.change_pct ?? 0) >= 0;
            const actionColor = a.action === "BUY" ? "text-green-400" : a.action === "SELL" ? "text-red-400" : "text-muted";

            return (
              <tr
                key={`${a.symbol}:${a.exchange}`}
                onClick={() => onSelectAsset(a.symbol, a.exchange)}
                className="border-b border-border/50 hover:bg-surface-2 cursor-pointer transition-colors"
              >
                {/* Symbol */}
                <td className="py-2 px-2">
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-foreground">{a.symbol}</span>
                    <span className="text-[9px] text-muted px-1 py-0.5 rounded bg-surface-2">{a.exchange}</span>
                  </div>
                </td>

                {/* LTP */}
                <td className="text-right py-2 px-2 font-mono text-foreground">
                  {a.ltp ? `${a.ltp.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—"}
                </td>

                {/* Change % */}
                <td className={cn("text-right py-2 px-2 font-mono", isUp ? "text-green-400" : "text-red-400")}>
                  {a.change_pct != null ? `${isUp ? "+" : ""}${a.change_pct.toFixed(2)}%` : "—"}
                </td>

                {/* Tide */}
                <td className={cn("text-center py-2 px-2 font-semibold", TIDE_COLORS[a.tide ?? ""] ?? "text-muted")}>
                  {a.tide ?? "—"}
                </td>

                {/* Impulse */}
                <td className="text-center py-2 px-2">
                  {a.impulse ? (
                    <span className={cn(
                      "inline-block w-2 h-2 rounded-full",
                      a.impulse === "bullish" ? "bg-green-500" :
                      a.impulse === "bearish" ? "bg-red-500" : "bg-blue-500"
                    )} />
                  ) : "—"}
                </td>

                {/* Signal/Action */}
                <td className={cn("text-center py-2 px-2 font-semibold", actionColor)}>
                  {a.action ?? "—"}
                </td>

                {/* Grade */}
                <td className="text-center py-2 px-2">
                  {a.grade ? (
                    <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-bold", GRADE_COLORS[a.grade] ?? "text-muted")}>
                      {a.grade}
                    </span>
                  ) : "—"}
                </td>

                {/* Confidence */}
                <td className="text-right py-2 px-2">
                  {a.confidence != null ? (
                    <div className="flex items-center justify-end gap-1">
                      <div className="w-10 h-1.5 bg-surface-2 rounded-full overflow-hidden">
                        <div
                          className={cn("h-full rounded-full", a.confidence >= 70 ? "bg-green-500" : a.confidence >= 50 ? "bg-amber-500" : "bg-red-500")}
                          style={{ width: `${a.confidence}%` }}
                        />
                      </div>
                      <span className="text-muted w-6 text-right">{a.confidence}%</span>
                    </div>
                  ) : "—"}
                </td>

                {/* Entry */}
                <td className="text-right py-2 px-2 font-mono text-muted">
                  {a.entry_price ? a.entry_price.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—"}
                </td>

                {/* Stop */}
                <td className="text-right py-2 px-2 font-mono text-red-400/60">
                  {a.stop_price ? a.stop_price.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
