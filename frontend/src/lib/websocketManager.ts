/**
 * WebSocket manager for pipeline and market data connections.
 * Non-React class — dispatches events to Zustand store.
 */

import { useTradingStore } from "@/store/useTradingStore";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const WS_BASE = BASE.replace(/^http/, "ws");

const HEARTBEAT_TIMEOUT = 30_000; // 30s — mark stale if no message
const MAX_RECONNECT_DELAY = 30_000;

export class WebSocketManager {
  private pipelineWs: WebSocket | null = null;
  private marketWs: WebSocket | null = null;
  private reconnectAttempts = 0;
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private destroyed = false;

  connect() {
    this.connectPipeline();
    this.connectMarket();
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
      useTradingStore.getState().setPipelineWsConnected(true);
      useTradingStore.getState().setDataFreshness("live");
      this.resetHeartbeat();
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
      this.schedulePipelineReconnect();
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
        if (candle && msg.symbol === store.symbol) {
          store.appendCandle({
            timestamp: candle.timestamp as string,
            open: candle.open as number,
            high: candle.high as number,
            low: candle.low as number,
            close: candle.close as number,
            volume: candle.volume as number,
          });
          // Auto-refresh indicators after new candle
          setTimeout(() => store.fetchIndicators(), 500);
        }
        break;
      }

      case "running_bar": {
        const bar = msg.bar as Record<string, unknown>;
        if (bar && msg.symbol === store.symbol) {
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
          // Indicator update from pipeline — could set directly
          // For now let the store's fetchIndicators handle it
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
        // Initial status on connect
        break;
      }

      case "heartbeat":
        break;
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
      // We keep this alive for backward compatibility
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
    if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.pipelineWs?.close();
    this.marketWs?.close();
    this.pipelineWs = null;
    this.marketWs = null;
  }
}
