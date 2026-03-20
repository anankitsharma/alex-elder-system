"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useTradingStore } from "@/store/useTradingStore";
import { SignalToast } from "./SignalToast";
import { TradeToast } from "./TradeToast";
import type { PipelineSignal } from "@/store/useTradingStore";
import type { TradeToastData } from "./TradeToast";
import { playAlert } from "@/lib/soundAlerts";

const AUTO_DISMISS_MS = 10_000;
const TRADE_DISMISS_MS = 8_000;
const MAX_TOASTS = 6;

interface ToastEntry {
  id: number;
  kind: "signal" | "trade";
  signal?: PipelineSignal;
  trade?: TradeToastData;
}

let _toastId = 0;

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const signals = useTradingStore((s) => s.signals);
  const tradeEvents = useTradingStore((s) => s.tradeEvents);
  const prevSignalLen = useRef(0);
  const prevTradeLen = useRef(0);

  // Watch for new signals
  useEffect(() => {
    if (signals.length > prevSignalLen.current && signals.length > 0) {
      const newSignal = signals[0];
      const id = ++_toastId;
      setToasts((t) => [...t, { id, kind: "signal" as const, signal: newSignal }].slice(-MAX_TOASTS));

      // Sound alert
      playAlert("signal");

      setTimeout(() => {
        setToasts((t) => t.filter((entry) => entry.id !== id));
      }, AUTO_DISMISS_MS);
    }
    prevSignalLen.current = signals.length;
  }, [signals]);

  // Watch for new trade events
  useEffect(() => {
    if (tradeEvents.length > prevTradeLen.current && tradeEvents.length > 0) {
      const newEvent = tradeEvents[0];
      const id = ++_toastId;
      setToasts((t) => [...t, { id, kind: "trade" as const, trade: newEvent }].slice(-MAX_TOASTS));

      // Sound alert based on event type
      if (newEvent.type === "order_filled") playAlert("trade");
      else if (newEvent.type === "order_rejected") playAlert("order_rejected");
      else if (newEvent.type === "position_closed") {
        if (newEvent.reason === "TARGET") playAlert("target_hit");
        else if (newEvent.reason === "STOP_LOSS") playAlert("stop_hit");
        else playAlert("eod_close");
      }

      setTimeout(() => {
        setToasts((t) => t.filter((entry) => entry.id !== id));
      }, TRADE_DISMISS_MS);
    }
    prevTradeLen.current = tradeEvents.length;
  }, [tradeEvents]);

  const dismiss = useCallback((id: number) => {
    setToasts((t) => t.filter((entry) => entry.id !== id));
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-3 right-3 z-50 flex flex-col gap-2">
      {toasts.map((entry) =>
        entry.kind === "signal" && entry.signal ? (
          <SignalToast
            key={entry.id}
            signal={entry.signal}
            onDismiss={() => dismiss(entry.id)}
          />
        ) : entry.kind === "trade" && entry.trade ? (
          <TradeToast
            key={entry.id}
            data={entry.trade}
            onDismiss={() => dismiss(entry.id)}
          />
        ) : null,
      )}
    </div>
  );
}
