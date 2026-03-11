"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { createMarketSocket } from "@/lib/api";

export interface TickData {
  token: string;
  ltp: number;
  [key: string]: any;
}

interface UseWebSocketResult {
  ticks: Record<string, TickData>;
  connected: boolean;
  lastMessage: TickData | null;
}

const MAX_TICKS = 500; // Bound memory — keep latest N tokens
const MAX_RETRIES = 15;
const MAX_BACKOFF = 30000; // 30s

export function useWebSocket(): UseWebSocketResult {
  const [ticks, setTicks] = useState<Record<string, TickData>>({});
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<TickData | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const unmountedRef = useRef(false);

  const connect = useCallback(() => {
    if (unmountedRef.current) return;

    try {
      const ws = createMarketSocket();
      wsRef.current = ws;

      ws.onopen = () => {
        if (unmountedRef.current) { ws.close(); return; }
        setConnected(true);
        retryRef.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as TickData;
          if (data.token) {
            setTicks((prev) => {
              const updated = { ...prev, [data.token]: data };
              // Prune if exceeding max
              const keys = Object.keys(updated);
              if (keys.length > MAX_TICKS) {
                const toRemove = keys.slice(0, keys.length - MAX_TICKS);
                for (const k of toRemove) delete updated[k];
              }
              return updated;
            });
            setLastMessage(data);
          }
        } catch {
          // Ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (unmountedRef.current) return;
        setConnected(false);

        if (retryRef.current < MAX_RETRIES) {
          const delay = Math.min(1000 * 2 ** retryRef.current, MAX_BACKOFF);
          retryRef.current++;
          setTimeout(connect, delay);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      if (!unmountedRef.current) setConnected(false);
    }
  }, []);

  useEffect(() => {
    unmountedRef.current = false;
    connect();
    return () => {
      unmountedRef.current = true;
      wsRef.current?.close();
    };
  }, [connect]);

  return { ticks, connected, lastMessage };
}
