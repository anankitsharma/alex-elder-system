"use client";

import { useEffect, useState, useRef } from "react";
import { useTradingStore } from "@/store/useTradingStore";
import { SignalToast } from "./SignalToast";
import type { PipelineSignal } from "@/store/useTradingStore";

const AUTO_DISMISS_MS = 10_000;

interface ToastEntry {
  id: number;
  signal: PipelineSignal;
}

let _toastId = 0;

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const signals = useTradingStore((s) => s.signals);
  const prevLen = useRef(0);

  // Watch for new signals
  useEffect(() => {
    if (signals.length > prevLen.current && signals.length > 0) {
      const newSignal = signals[0]; // Newest is first
      const id = ++_toastId;
      setToasts((t) => [...t, { id, signal: newSignal }].slice(-5));

      // Auto-dismiss
      setTimeout(() => {
        setToasts((t) => t.filter((entry) => entry.id !== id));
      }, AUTO_DISMISS_MS);
    }
    prevLen.current = signals.length;
  }, [signals]);

  const dismiss = (id: number) => {
    setToasts((t) => t.filter((entry) => entry.id !== id));
  };

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-3 right-3 z-50 flex flex-col gap-2">
      {toasts.map((entry) => (
        <SignalToast
          key={entry.id}
          signal={entry.signal}
          onDismiss={() => dismiss(entry.id)}
        />
      ))}
    </div>
  );
}
