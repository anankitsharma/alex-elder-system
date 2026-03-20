"use client";

import type { CommandCenterAsset } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  assets: CommandCenterAsset[];
  onSelectAsset: (symbol: string, exchange: string) => void;
}

const TF_LABELS: Record<string, string> = {
  "1w": "Weekly", "1d": "Daily", "4h": "4H", "1h": "Hourly",
  "15m": "15min", "5m": "5min", "1m": "1min",
};

function ScreenDot({ active, label }: { active: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={cn("w-1.5 h-1.5 rounded-full", active ? "bg-green-500" : "bg-red-500/40")} />
      <span className="text-[9px] text-muted">{label}</span>
    </span>
  );
}

function AssetCard({ asset, onSelect }: { asset: CommandCenterAsset; onSelect: () => void }) {
  const a = asset;
  const al = a.alignment;
  const level = al?.level ?? 0;
  const isUp = (a.change_pct ?? 0) >= 0;
  const tfs = a.screen_timeframes || {};

  const borderColor = level === 3 ? "border-green-500/60" : level === 2 ? "border-orange-500/40" : level === 1 ? "border-amber-500/30" : "border-border";

  return (
    <div
      onClick={onSelect}
      className={cn(
        "rounded-lg border bg-surface p-3 cursor-pointer hover:bg-surface-2 transition-colors",
        borderColor,
        level === 3 && "ring-1 ring-green-500/20",
      )}
    >
      {/* Header: Symbol + LTP + Change */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="font-bold text-foreground text-[13px]">{a.symbol}</span>
          <span className="text-[9px] text-muted px-1 py-0.5 rounded bg-surface-2">{a.exchange}</span>
          {a.grade && (
            <span className={cn(
              "text-[9px] px-1 py-0.5 rounded font-bold",
              a.grade === "A" || a.grade === "B" ? "bg-green-500/15 text-green-400" :
              a.grade === "C" ? "bg-amber-500/15 text-amber-400" : "bg-red-500/15 text-red-400"
            )}>
              {a.grade}
            </span>
          )}
        </div>
        <div className="text-right">
          <div className="font-mono text-foreground text-[12px]">
            {a.ltp ? `₹${a.ltp.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—"}
          </div>
          <div className={cn("text-[10px] font-mono", isUp ? "text-green-400" : "text-red-400")}>
            {a.change_pct != null ? `${isUp ? "+" : ""}${a.change_pct.toFixed(2)}%` : ""}
          </div>
        </div>
      </div>

      {/* Alignment bar */}
      <div className="flex items-center gap-2 mb-2">
        <div className="flex items-center gap-1">
          {[1, 2, 3].map((s) => (
            <span
              key={s}
              className={cn(
                "w-5 h-1.5 rounded-full",
                (al && (al as any)[`screen${s}`]) ? "bg-green-500" : "bg-surface-2",
              )}
            />
          ))}
        </div>
        <span className={cn(
          "text-[9px] font-semibold",
          level === 3 ? "text-green-400" : level === 2 ? "text-orange-400" : level === 1 ? "text-amber-400" : "text-muted",
        )}>
          {al?.description ?? "No setup"}
        </span>
      </div>

      {/* Three screens detail */}
      <div className="space-y-1.5">
        {/* Screen 1 */}
        <div className="flex items-center justify-between text-[10px]">
          <div className="flex items-center gap-1.5">
            <ScreenDot active={al?.screen1 ?? false} label="S1" />
            <span className="text-muted">{TF_LABELS[tfs["1"] ?? ""] ?? tfs["1"] ?? "—"}</span>
            <span className="text-muted">Tide</span>
          </div>
          <span className={cn(
            "font-semibold",
            a.tide === "BULLISH" ? "text-green-400" : a.tide === "BEARISH" ? "text-red-400" : "text-muted",
          )}>
            {a.tide ?? "—"}
          </span>
        </div>

        {/* Screen 2 */}
        <div className="flex items-center justify-between text-[10px]">
          <div className="flex items-center gap-1.5">
            <ScreenDot active={al?.screen2 ?? false} label="S2" />
            <span className="text-muted">{TF_LABELS[tfs["2"] ?? ""] ?? tfs["2"] ?? "—"}</span>
            <span className="text-muted">Wave</span>
          </div>
          <span className={cn(
            "font-semibold",
            a.wave_signal === "BUY" ? "text-green-400" : a.wave_signal === "SELL" ? "text-red-400" : "text-muted",
          )}>
            {a.wave_signal ?? "—"}
          </span>
        </div>

        {/* Screen 3 */}
        <div className="flex items-center justify-between text-[10px]">
          <div className="flex items-center gap-1.5">
            <ScreenDot active={al?.screen3 ?? false} label="S3" />
            <span className="text-muted">{TF_LABELS[tfs["3"] ?? ""] ?? tfs["3"] ?? "—"}</span>
            <span className="text-muted">Entry</span>
          </div>
          <span className={cn(
            "font-semibold",
            a.action === "BUY" ? "text-green-400" : a.action === "SELL" ? "text-red-400" : "text-muted",
          )}>
            {a.action ?? "WAIT"}
          </span>
        </div>
      </div>

      {/* Entry/Stop if actionable */}
      {a.entry_price && a.stop_price && a.action !== "WAIT" && (
        <div className="mt-2 pt-2 border-t border-border/50 flex items-center justify-between text-[10px]">
          <span className="text-muted">
            Entry: <span className="text-foreground font-mono">₹{a.entry_price.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
          </span>
          <span className="text-muted">
            Stop: <span className="text-red-400 font-mono">₹{a.stop_price.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
          </span>
          {a.confidence != null && (
            <span className={cn(
              "font-bold",
              a.confidence >= 70 ? "text-green-400" : a.confidence >= 50 ? "text-amber-400" : "text-muted"
            )}>
              {a.confidence}%
            </span>
          )}
        </div>
      )}

      {/* Impulse indicator */}
      {a.impulse && (
        <div className="mt-1.5 flex items-center gap-1 text-[9px] text-muted">
          <span className={cn(
            "w-2 h-2 rounded-full",
            a.impulse === "bullish" ? "bg-green-500" : a.impulse === "bearish" ? "bg-red-500" : "bg-blue-500"
          )} />
          Impulse: {a.impulse}
        </div>
      )}
    </div>
  );
}

export default function AssetStatusCards({ assets, onSelectAsset }: Props) {
  if (assets.length === 0) return null;

  // Sort: full alignment first
  const sorted = [...assets].sort((a, b) => {
    const la = a.alignment?.level ?? 0;
    const lb = b.alignment?.level ?? 0;
    if (lb !== la) return lb - la;
    return a.symbol.localeCompare(b.symbol);
  });

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
      {sorted.map((a) => (
        <AssetCard
          key={`${a.symbol}:${a.exchange}`}
          asset={a}
          onSelect={() => onSelectAsset(a.symbol, a.exchange)}
        />
      ))}
    </div>
  );
}
