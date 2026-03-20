"use client";

import { cn } from "@/lib/utils";
import { X } from "lucide-react";

export type TradeToastType =
  | "order_filled"
  | "order_rejected"
  | "order_partial_fill"
  | "position_closed"
  | "trailing_stop"
  | "error";

export interface TradeToastData {
  type: TradeToastType;
  symbol: string;
  message: string;
  detail?: string;
  pnl?: number;
  reason?: string;
}

interface TradeToastProps {
  data: TradeToastData;
  onDismiss: () => void;
}

const TYPE_STYLES: Record<TradeToastType, { border: string; icon: string; label: string }> = {
  order_filled: {
    border: "border-green-500/30",
    icon: "✅",
    label: "Order Filled",
  },
  order_rejected: {
    border: "border-red-500/30",
    icon: "❌",
    label: "Order Rejected",
  },
  order_partial_fill: {
    border: "border-amber-500/30",
    icon: "⏳",
    label: "Partial Fill",
  },
  position_closed: {
    border: "border-blue-500/30",
    icon: "📤",
    label: "Position Closed",
  },
  trailing_stop: {
    border: "border-gray-500/30",
    icon: "📐",
    label: "Stop Updated",
  },
  error: {
    border: "border-red-500/40",
    icon: "⚠️",
    label: "Error",
  },
};

export function TradeToast({ data, onDismiss }: TradeToastProps) {
  const style = TYPE_STYLES[data.type] || TYPE_STYLES.error;

  // Override icon for position_closed based on reason/pnl
  let icon = style.icon;
  if (data.type === "position_closed") {
    if (data.reason === "STOP_LOSS") icon = "🛑";
    else if (data.reason === "TARGET") icon = "🎯";
    else if (data.reason === "EOD") icon = "🔔";
    else if (data.reason === "FLIP") icon = "🔄";
  }

  return (
    <div
      className={cn(
        "relative w-72 rounded-lg bg-surface border shadow-lg p-3 animate-in slide-in-from-right-full duration-300",
        style.border,
      )}
    >
      <button
        onClick={onDismiss}
        className="absolute top-2 right-2 text-muted hover:text-foreground"
      >
        <X className="w-3.5 h-3.5" />
      </button>

      <div className="flex items-center gap-2 mb-1">
        <span className="text-sm">{icon}</span>
        <span className="text-xs font-bold text-foreground">{style.label}</span>
        <span className="text-xs text-muted">{data.symbol}</span>
      </div>

      <div className="text-[10px] text-muted">{data.message}</div>

      {data.detail && (
        <div className="text-[10px] text-muted mt-0.5">{data.detail}</div>
      )}

      {data.pnl !== undefined && data.pnl !== null && (
        <div
          className={cn(
            "text-xs font-bold mt-1",
            data.pnl > 0 ? "text-green-500" : data.pnl < 0 ? "text-red-500" : "text-muted",
          )}
        >
          P&L: {data.pnl > 0 ? "+" : ""}
          {data.pnl.toLocaleString("en-IN", { style: "currency", currency: "INR" })}
        </div>
      )}
    </div>
  );
}
