/**
 * Bootstrap hook — initializes WebSocket manager and loads initial data.
 * Called once in page.tsx.
 */

import { useEffect, useRef, useState } from "react";
import { useTradingStore } from "@/store/useTradingStore";
import { WebSocketManager } from "@/lib/websocketManager";
import { fetchHealth, fetchTradingMode } from "@/lib/api";

// Module-level singleton so components can access it
let _wsManager: WebSocketManager | null = null;
export function getWsManager(): WebSocketManager | null {
  return _wsManager;
}

export function usePipelineInit() {
  const [ready, setReady] = useState(false);
  const wsRef = useRef<WebSocketManager | null>(null);
  const store = useTradingStore();

  useEffect(() => {
    // Initialize WebSocket manager
    const ws = new WebSocketManager();
    wsRef.current = ws;
    _wsManager = ws;
    ws.connect();

    // Load initial data via REST
    store.fetchCandles();
    store.fetchIndicators();

    // Auto-track the initial symbol on the pipeline
    const { symbol, exchange } = useTradingStore.getState();
    ws.trackSymbol(symbol, exchange);

    // Load backend settings
    (async () => {
      try {
        const health = await fetchHealth();
        store.setApiOnline(true);
        if (health.feed_connected) {
          store.setBrokerConnected(true);
          store.setDataFreshness("live");
        } else {
          store.setDataFreshness(health.status === "ok" ? "demo" : "disconnected");
        }
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
        const health = await fetchHealth();
        store.setApiOnline(true);
        if (health.feed_connected) {
          store.setBrokerConnected(true);
        }
      } catch {
        store.setApiOnline(false);
        store.setDataFreshness("disconnected");
      }
    }, 30_000);

    // Clean up on page close
    const onBeforeUnload = () => {
      ws.destroy();
    };
    window.addEventListener("beforeunload", onBeforeUnload);

    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      ws.destroy();
      _wsManager = null;
      clearInterval(healthInterval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { ready, wsManager: wsRef.current };
}
