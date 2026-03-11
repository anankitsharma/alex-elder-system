/**
 * WebSocket manager for pipeline and market data connections.
 * Non-React class — dispatches events to Zustand store.
 */

import { useTradingStore } from "@/store/useTradingStore";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const WS_BASE = BASE.replace(/^http/, "ws");

const HEARTBEAT_TIMEOUT = 45_000; // 45s — mark stale if no message (backend sends every 15s)
const MAX_RECONNECT_DELAY = 30_000;
const REST_POLL_AFTER = 60_000; // Start REST polling if WS down > 60s

export class WebSocketManager {
  private pipelineWs: WebSocket | null = null;
  private marketWs: WebSocket | null = null;
  private reconnectAttempts = 0;
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private disconnectedSince: number | null = null;
  private destroyed = false;

  // Track what symbol we're subscribed to for resubscribe on reconnect
  private trackedSymbol: string | null = null;
  private trackedExchange: string | null = null;

  connect() {
    this.connectPipeline();
    this.connectMarket();
  }

  // ── Symbol tracking ─────────────────────────────────────────

  trackSymbol(symbol: string, exchange: string) {
    // Untrack previous if different
    if (this.trackedSymbol && (this.trackedSymbol !== symbol || this.trackedExchange !== exchange)) {
      this.sendPipelineAction("stop_tracking", {
        symbol: this.trackedSymbol,
        exchange: this.trackedExchange,
      });
    }

    this.trackedSymbol = symbol;
    this.trackedExchange = exchange;

    this.sendPipelineAction("start_tracking", { symbol, exchange });
  }

  untrackSymbol() {
    if (this.trackedSymbol) {
      this.sendPipelineAction("stop_tracking", {
        symbol: this.trackedSymbol,
        exchange: this.trackedExchange,
      });
      this.trackedSymbol = null;
      this.trackedExchange = null;
    }
  }

  // ── Pipeline WebSocket (/ws/pipeline) ──────────────────────

  private connectPipeline() {
    if (this.destroyed) return;
    try {
      this.pipelineWs = new WebSocket(`${WS_BASE}/ws/pipeline`);
    } catch {
      this.schedulePipelineReconnect();
      return;
    }

    this.pipelineWs.onopen = () => {
      this.reconnectAttempts = 0;
      this.disconnectedSince = null;
      this.stopPolling();
      useTradingStore.getState().setPipelineWsConnected(true);
      useTradingStore.getState().setDataFreshness("live");
      this.resetHeartbeat();

      // Resubscribe to tracked symbol on reconnect
      if (this.trackedSymbol) {
        this.sendPipelineAction("start_tracking", {
          symbol: this.trackedSymbol,
          exchange: this.trackedExchange,
        });
      }
    };

    this.pipelineWs.onmessage = (ev) => {
      this.resetHeartbeat();
      try {
        const msg = JSON.parse(ev.data);
        this.handlePipelineMessage(msg);
      } catch {
        // Non-JSON message — ignore
      }
    };

    this.pipelineWs.onclose = () => {
      useTradingStore.getState().setPipelineWsConnected(false);
      if (!this.disconnectedSince) {
        this.disconnectedSince = Date.now();
      }
      this.schedulePipelineReconnect();
      this.maybeStartPolling();
    };

    this.pipelineWs.onerror = () => {
      // onclose will fire after this
    };
  }

  private handlePipelineMessage(msg: Record<string, unknown>) {
    const store = useTradingStore.getState();
    const type = msg.type as string;

    switch (type) {
      case "candle": {
        const candle = msg.candle as Record<string, unknown>;
        const timeframe = msg.timeframe as string;
        if (candle && msg.symbol === store.symbol) {
          const candleData = {
            timestamp: candle.timestamp as string,
            open: candle.open as number,
            high: candle.high as number,
            low: candle.low as number,
            close: candle.close as number,
            volume: candle.volume as number,
          };
          // If timeframe matches current interval, update main store
          if (timeframe === store.interval) {
            store.appendCandle(candleData);
            // Auto-refresh indicators after new candle
            setTimeout(() => store.fetchIndicators(), 500);
          }
        }
        break;
      }

      case "running_bar": {
        const bar = msg.bar as Record<string, unknown>;
        const timeframe = msg.timeframe as string;
        if (bar && msg.symbol === store.symbol && timeframe === store.interval) {
          store.updateLastCandle({
            timestamp: bar.timestamp as string,
            open: bar.open as number,
            high: bar.high as number,
            low: bar.low as number,
            close: bar.close as number,
            volume: bar.volume as number,
          });
        }
        break;
      }

      case "indicators": {
        if (msg.symbol === store.symbol && msg.data) {
          const timeframe = msg.timeframe as string;
          if (timeframe === store.interval) {
            // Set indicators directly from WebSocket — no REST round-trip
            store.setIndicators(msg.data as import("@/lib/api").IndicatorData);
          }
        }
        break;
      }

      case "signal": {
        const analysis = msg.analysis as Record<string, unknown>;
        if (analysis && msg.symbol === store.symbol) {
          store.setTripleScreen(analysis as unknown as import("@/lib/api").TripleScreenResult);
        }
        break;
      }

      case "trade_alert": {
        store.addSignal({
          symbol: msg.symbol as string,
          action: msg.action as string,
          grade: msg.grade as string,
          confidence: msg.confidence as number,
          entry_price: msg.entry_price as number | undefined,
          stop_price: msg.stop_price as number | undefined,
          shares: msg.shares as number | undefined,
          signal_id: msg.signal_id as number | undefined,
          timestamp: new Date().toISOString(),
        });
        break;
      }

      case "order": {
        // Refresh positions/orders when a pipeline order fills
        store.refreshPositions();
        store.refreshOrders();
        break;
      }

      case "pipeline_status": {
        // Update broker connection status from pipeline
        if (typeof msg.feed_connected === "boolean") {
          store.setBrokerConnected(msg.feed_connected as boolean);
        }
        break;
      }

      case "heartbeat": {
        // Update broker status from heartbeat
        if (typeof msg.feed_connected === "boolean") {
          store.setBrokerConnected(msg.feed_connected as boolean);
          // If feed is connected and sending data, we're live
          const age = msg.feed_last_data_age as number;
          if (msg.feed_connected && age >= 0 && age < 60) {
            store.setDataFreshness("live");
          } else if (msg.feed_connected) {
            store.setDataFreshness("stale");
          }
        }
        break;
      }
    }
  }

  private resetHeartbeat() {
    if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
    this.heartbeatTimer = setTimeout(() => {
      useTradingStore.getState().setDataFreshness("stale");
    }, HEARTBEAT_TIMEOUT);
  }

  private schedulePipelineReconnect() {
    if (this.destroyed) return;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, MAX_RECONNECT_DELAY);
    this.reconnectAttempts++;
    this.reconnectTimer = setTimeout(() => this.connectPipeline(), delay);
  }

  // ── REST polling fallback ───────────────────────────────────

  private maybeStartPolling() {
    if (this.destroyed || this.pollTimer) return;
    // Start polling if WS has been down for > 60s
    setTimeout(() => {
      if (this.disconnectedSince && (Date.now() - this.disconnectedSince) > REST_POLL_AFTER) {
        this.startPolling();
      }
    }, REST_POLL_AFTER);
  }

  private startPolling() {
    if (this.pollTimer || this.destroyed) return;
    const store = useTradingStore.getState();
    if (!store.apiOnline) return;

    this.pollTimer = setInterval(() => {
      const s = useTradingStore.getState();
      if (s.pipelineWsConnected) {
        this.stopPolling();
        return;
      }
      s.fetchCandles();
      s.fetchIndicators();
    }, 30_000);
  }

  private stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  // ── Market WebSocket (/ws/market) — legacy tick stream ─────

  private connectMarket() {
    if (this.destroyed) return;
    try {
      this.marketWs = new WebSocket(`${WS_BASE}/ws/market`);
    } catch {
      setTimeout(() => this.connectMarket(), 5000);
      return;
    }

    this.marketWs.onopen = () => {
      useTradingStore.getState().setWsConnected(true);
    };

    this.marketWs.onmessage = () => {
      // Raw ticks — existing useWebSocket hook handles this too
    };

    this.marketWs.onclose = () => {
      useTradingStore.getState().setWsConnected(false);
      if (!this.destroyed) {
        setTimeout(() => this.connectMarket(), 5000);
      }
    };

    this.marketWs.onerror = () => {};
  }

  // ── Control ────────────────────────────────────────────────

  sendPipelineAction(action: string, data: Record<string, unknown> = {}) {
    if (this.pipelineWs?.readyState === WebSocket.OPEN) {
      this.pipelineWs.send(JSON.stringify({ action, ...data }));
    }
  }

  destroy() {
    this.destroyed = true;
    this.stopPolling();
    if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.pipelineWs?.close();
    this.marketWs?.close();
    this.pipelineWs = null;
    this.marketWs = null;
  }
}
