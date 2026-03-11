/**
 * Bootstrap hook — initializes WebSocket manager and loads initial data.
 * Called once in page.tsx.
 */

import { useEffect, useRef, useState } from "react";
import { useTradingStore } from "@/store/useTradingStore";
import { WebSocketManager } from "@/lib/websocketManager";
import { fetchHealth, fetchTradingMode } from "@/lib/api";

export function usePipelineInit() {
  const [ready, setReady] = useState(false);
  const wsRef = useRef<WebSocketManager | null>(null);
  const store = useTradingStore();

  useEffect(() => {
    // Initialize WebSocket manager
    const ws = new WebSocketManager();
    wsRef.current = ws;
    ws.connect();

    // Load initial data
    store.fetchCandles();
    store.fetchIndicators();

    // Load backend settings
    (async () => {
      try {
        const health = await fetchHealth();
        store.setApiOnline(true);
        store.setDataFreshness(
          health.status === "ok" ? "live" : "demo"
        );
      } catch {
        store.setApiOnline(false);
        store.setDataFreshness("disconnected");
      }

      try {
        const mode = await fetchTradingMode();
        store.setTradingMode(mode.mode);
      } catch {
        // Keep default PAPER
      }

      setReady(true);
    })();

    // Health polling (every 30s)
    const healthInterval = setInterval(async () => {
      try {
        await fetchHealth();
        store.setApiOnline(true);
      } catch {
        store.setApiOnline(false);
        store.setDataFreshness("disconnected");
      }
    }, 30_000);

    return () => {
      ws.destroy();
      clearInterval(healthInterval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { ready, wsManager: wsRef.current };
}
