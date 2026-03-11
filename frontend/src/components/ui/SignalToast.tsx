"use client";

import { cn } from "@/lib/utils";
import { X } from "lucide-react";
import type { PipelineSignal } from "@/store/useTradingStore";

interface SignalToastProps {
  signal: PipelineSignal;
  onDismiss: () => void;
  onDetails?: () => void;
}

const GRADE_COLORS: Record<string, string> = {
  A: "text-green-500",
  B: "text-emerald-500",
  C: "text-amber-500",
  D: "text-red-500",
};

export function SignalToast({ signal, onDismiss, onDetails }: SignalToastProps) {
  const isBuy = signal.action === "BUY";
  const borderColor = isBuy ? "border-green-500/30" : signal.action === "SELL" ? "border-red-500/30" : "border-border";
  const actionColor = isBuy ? "text-green-500" : signal.action === "SELL" ? "text-red-500" : "text-muted";

  return (
    <div
      className={cn(
        "relative w-72 rounded-lg bg-surface border shadow-lg p-3 animate-in slide-in-from-right-full duration-300",
        borderColor
      )}
    >
      <button
        onClick={onDismiss}
        className="absolute top-2 right-2 text-muted hover:text-foreground"
      >
        <X className="w-3.5 h-3.5" />
      </button>

      <div className="flex items-center gap-2 mb-1.5">
        <span className={cn("text-xs font-bold", actionColor)}>
          {signal.action}
        </span>
        <span className="text-xs font-semibold text-foreground">
          {signal.symbol}
        </span>
        <span className={cn("text-xs font-bold", GRADE_COLORS[signal.grade] || "text-muted")}>
          Grade {signal.grade}
        </span>
      </div>

      <div className="text-[10px] text-muted space-y-0.5">
        <div>Confidence: {signal.confidence}%</div>
        {signal.entry_price != null && <div>Entry: {signal.entry_price.toFixed(2)}</div>}
        {signal.stop_price != null && <div>Stop: {signal.stop_price.toFixed(2)}</div>}
        {signal.shares != null && signal.shares > 0 && <div>Qty: {signal.shares}</div>}
      </div>

      {onDetails && (
        <button
          onClick={onDetails}
          className="mt-2 text-[10px] font-medium text-accent hover:underline"
        >
          View Details
        </button>
      )}
    </div>
  );
}
