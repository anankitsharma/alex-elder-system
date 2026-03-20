/**
 * WebSocket manager for pipeline and market data connections.
 * Non-React class — dispatches events to Zustand store.
 *
 * Features:
 * - Multi-timeframe routing (all screen timeframes, not just selected interval)
 * - Running bar updates bypass candle array (no chart flicker)
 * - Tick counting for activity indicator
 * - Gap backfill on reconnect
 * - Exponential backoff with jitter
 * - REST polling fallback when WS is down
 */

import { useTradingStore } from "@/store/useTradingStore";
import { useNotificationStore } from "@/store/useNotificationStore";
import type { CandleData, IndicatorData } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const WS_BASE = BASE.replace(/^http/, "ws");

const HEARTBEAT_TIMEOUT = 45_000;
const MAX_RECONNECT_DELAY = 30_000;
const MAX_RECONNECT_ATTEMPTS = 50;
const REST_POLL_INTERVAL = 5_000; // Poll every 5s when WS down (fast fallback)
const REST_POLL_AFTER = 15_000;   // Start polling after 15s disconnected

export class WebSocketManager {
  private pipelineWs: WebSocket | null = null;
  private marketWs: WebSocket | null = null;
  private reconnectAttempts = 0;
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private disconnectedSince: number | null = null;
  private destroyed = false;

  // Running bar batching (requestAnimationFrame)
  private pendingRunningBar: CandleData | null = null;
  private rafScheduled = false;

  // Track what symbol we're subscribed to for resubscribe on reconnect
  private trackedSymbol: string | null = null;
  private trackedExchange: string | null = null;

  connect() {
    this.connectPipeline();
    this.connectMarket();
  }

  // ── Symbol tracking ─────────────────────────────────────────

  trackSymbol(symbol: string, exchange: string) {
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

    const store = useTradingStore.getState();
    store.setWsState("connecting");

    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('elder_token') : null;
      const tokenParam = token ? `?token=${token}` : '';
      this.pipelineWs = new WebSocket(`${WS_BASE}/ws/pipeline${tokenParam}`);
    } catch {
      this.schedulePipelineReconnect();
      return;
    }

    this.pipelineWs.onopen = () => {
      const store = useTradingStore.getState();
      const wasDisconnected = this.disconnectedSince;

      this.reconnectAttempts = 0;
      this.stopPolling();
      store.setPipelineWsConnected(true);
      store.setWsState("connected");
      store.setDataFreshness("live");
      this.resetHeartbeat();

      // Resubscribe to tracked symbol on reconnect
      if (this.trackedSymbol && this.pipelineWs?.readyState === WebSocket.OPEN) {
        this.sendPipelineAction("start_tracking", {
          symbol: this.trackedSymbol,
          exchange: this.trackedExchange,
        });

        // Request backfill if we were disconnected
        if (wasDisconnected) {
          const since = new Date(wasDisconnected).toISOString();
          this.sendPipelineAction("backfill", {
            symbol: this.trackedSymbol,
            exchange: this.trackedExchange,
            since,
          });
        }
      }

      this.disconnectedSince = null;
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
      const store = useTradingStore.getState();
      store.setPipelineWsConnected(false);
      store.setWsState(this.reconnectAttempts > 0 ? "reconnecting" : "disconnected");
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
    const notifStore = useNotificationStore.getState();
    const type = msg.type as string;

    switch (type) {
      case "candle": {
        const candle = msg.candle as Record<string, unknown>;
        const timeframe = msg.timeframe as string;
        if (candle && msg.symbol === store.symbol) {
          const candleData: CandleData = {
            timestamp: candle.timestamp as string,
            open: candle.open as number,
            high: candle.high as number,
            low: candle.low as number,
            close: candle.close as number,
            volume: candle.volume as number,
          };

          // Update per-timeframe screen data (for Three Screen view)
          store.appendScreenCandle(timeframe, candleData);

          // Also update main store if timeframe matches selected interval
          if (timeframe === store.interval) {
            store.appendCandle(candleData);
          }
        }
        break;
      }

      case "running_bar": {
        const bar = msg.bar as Record<string, unknown>;
        const timeframe = msg.timeframe as string;
        if (bar && msg.symbol === store.symbol) {
          const candleData: CandleData = {
            timestamp: bar.timestamp as string,
            open: bar.open as number,
            high: bar.high as number,
            low: bar.low as number,
            close: bar.close as number,
            volume: bar.volume as number,
          };

          // Buffer running bar and flush once per animation frame (~16ms)
          // This replaces the 500ms throttle for much lower latency
          if (timeframe === store.interval) {
            this.pendingRunningBar = candleData;
            if (!this.rafScheduled) {
              this.rafScheduled = true;
              requestAnimationFrame(() => {
                if (this.pendingRunningBar) {
                  useTradingStore.getState().updateRunningBar(this.pendingRunningBar);
                  useTradingStore.getState().incrementTick();
                  this.pendingRunningBar = null;
                }
                this.rafScheduled = false;
              });
            }
          }
        }
        break;
      }

      case "indicators": {
        if (msg.symbol === store.symbol && msg.data) {
          const timeframe = msg.timeframe as string;
          const data = msg.data as IndicatorData;

          // Update per-timeframe screen data
          store.setScreenIndicators(timeframe, data);

          // Update main store if matching interval
          if (timeframe === store.interval) {
            store.setIndicators(data);
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
        const sym = msg.symbol as string;
        const action = msg.action as string;
        const grade = msg.grade as string;
        const conf = msg.confidence as number;
        store.addSignal({
          symbol: sym, action, grade, confidence: conf,
          entry_price: msg.entry_price as number | undefined,
          stop_price: msg.stop_price as number | undefined,
          shares: msg.shares as number | undefined,
          signal_id: msg.signal_id as number | undefined,
          timestamp: new Date().toISOString(),
        });
        notifStore.addNotification({
          category: "signal",
          priority: "normal",
          title: `${action} ${sym}`,
          message: `Grade ${grade} | Confidence ${conf}%`,
          detail: msg.entry_price ? `Entry ₹${Number(msg.entry_price).toFixed(2)}` : undefined,
          symbol: sym,
          icon: action === "BUY" ? "🟢" : "🔴",
        });
        break;
      }

      case "order": {
        store.refreshPositions();
        store.refreshOrders();
        const orderMode = (msg.mode as string) || "PAPER";
        const orderStatus = (msg.status as string) || "COMPLETE";
        const orderSym = msg.symbol as string;
        if (orderStatus === "COMPLETE") {
          store.addTradeEvent({
            type: "order_filled",
            symbol: orderSym,
            message: `${msg.direction} x${msg.quantity} @ ₹${Number(msg.price || 0).toFixed(2)}`,
            detail: `Stop: ₹${Number(msg.stop_price || 0).toFixed(2)} | ${orderMode}`,
          });
          notifStore.addNotification({
            category: "trade",
            priority: orderMode === "LIVE" ? "high" : "normal",
            title: `Trade: ${msg.direction} ${orderSym}`,
            message: `Qty ${msg.quantity} @ ₹${Number(msg.price || 0).toFixed(2)}`,
            detail: `Stop ₹${Number(msg.stop_price || 0).toFixed(2)} | Target ₹${Number(msg.target_price || 0).toFixed(2)}`,
            symbol: orderSym,
            icon: msg.direction === "BUY" ? "📈" : "📉",
          });
        }
        break;
      }

      case "order_filled": {
        store.refreshPositions();
        store.refreshOrders();
        const filledSym = msg.symbol as string;
        store.addTradeEvent({
          type: "order_filled",
          symbol: filledSym,
          message: `Filled @ ₹${Number(msg.filled_price || 0).toFixed(2)} x${msg.filled_quantity}`,
        });
        notifStore.addNotification({
          category: "trade",
          priority: "normal",
          title: `Order Filled: ${filledSym}`,
          message: `₹${Number(msg.filled_price || 0).toFixed(2)} x${msg.filled_quantity}`,
          symbol: filledSym,
          icon: "✅",
        });
        break;
      }

      case "order_rejected": {
        const rejSym = msg.symbol as string;
        store.addTradeEvent({
          type: "order_rejected",
          symbol: rejSym,
          message: `Order ${msg.order_id || ""} ${msg.status || "REJECTED"}`,
          detail: (msg.reason as string) || undefined,
        });
        notifStore.addNotification({
          category: "error",
          priority: "critical",
          title: `Order Rejected: ${rejSym}`,
          message: `${msg.order_id || ""} ${msg.status || "REJECTED"}`,
          detail: (msg.reason as string) || undefined,
          symbol: rejSym,
          icon: "❌",
        });
        break;
      }

      case "order_partial_fill": {
        const partSym = msg.symbol as string;
        store.addTradeEvent({
          type: "order_partial_fill",
          symbol: partSym,
          message: `${msg.filled_quantity}/${msg.total_quantity} filled @ ₹${Number(msg.filled_price || 0).toFixed(2)}`,
        });
        notifStore.addNotification({
          category: "trade",
          priority: "normal",
          title: `Partial Fill: ${partSym}`,
          message: `${msg.filled_quantity}/${msg.total_quantity} @ ₹${Number(msg.filled_price || 0).toFixed(2)}`,
          symbol: partSym,
          icon: "⏳",
        });
        break;
      }

      case "position_closed": {
        store.refreshPositions();
        const closeSym = msg.symbol as string;
        const pnl = msg.pnl as number;
        const reason = msg.reason as string;
        store.addTradeEvent({
          type: "position_closed",
          symbol: closeSym,
          message: `${msg.direction} closed @ ₹${Number(msg.exit_price || 0).toFixed(2)}`,
          reason, pnl,
        });
        const reasonIcons: Record<string, string> = {
          STOP_LOSS: "🛑", TARGET: "🎯", EOD: "🔔", FLIP: "🔄",
        };
        notifStore.addNotification({
          category: "position",
          priority: "high",
          title: `${reason === "TARGET" ? "Target Hit" : reason === "STOP_LOSS" ? "Stop Hit" : reason === "EOD" ? "EOD Close" : reason}: ${closeSym}`,
          message: `${msg.direction} @ ₹${Number(msg.exit_price || 0).toFixed(2)}`,
          detail: `Entry ₹${Number(msg.entry_price || 0).toFixed(2)}`,
          symbol: closeSym,
          pnl,
          icon: reasonIcons[reason] || "📤",
        });
        break;
      }

      case "trailing_stop_updated": {
        const tsSym = msg.symbol as string;
        store.addTradeEvent({
          type: "trailing_stop",
          symbol: tsSym,
          message: `Stop: ₹${Number(msg.old_stop || 0).toFixed(2)} → ₹${Number(msg.new_stop || 0).toFixed(2)}`,
          detail: `LTP: ₹${Number(msg.ltp || 0).toFixed(2)}`,
        });
        // Low priority — don't push to notification center (too noisy)
        break;
      }

      case "command_center": {
        const assets = msg.assets as import("@/lib/api").CommandCenterAsset[];
        if (Array.isArray(assets)) {
          store.setCommandCenterAssets(assets);
        }
        break;
      }

      case "pipeline_status": {
        if (typeof msg.feed_connected === "boolean") {
          store.setBrokerConnected(msg.feed_connected as boolean);
        }
        break;
      }

      case "heartbeat": {
        if (typeof msg.feed_connected === "boolean") {
          store.setBrokerConnected(msg.feed_connected as boolean);
          const age = msg.feed_last_data_age as number;
          if (msg.feed_connected && age >= 0 && age < 60) {
            store.setDataFreshness("live");
          } else if (msg.feed_connected) {
            store.setDataFreshness("stale");
          }
        }
        break;
      }

      case "backfill_response": {
        // Merge backfill candles into store
        this.handleBackfillResponse(msg);
        break;
      }
    }
  }

  private handleBackfillResponse(msg: Record<string, unknown>) {
    const store = useTradingStore.getState();
    const candles = msg.candles as Record<string, Record<string, unknown>[]>;
    if (!candles) return;

    // candles is { "1d": [...], "1h": [...], "15m": [...] }
    for (const [tf, bars] of Object.entries(candles)) {
      if (!Array.isArray(bars) || bars.length === 0) continue;

      const candleData: CandleData[] = bars.map((b) => ({
        timestamp: b.timestamp as string,
        open: b.open as number,
        high: b.high as number,
        low: b.low as number,
        close: b.close as number,
        volume: b.volume as number,
      }));

      // Append each bar to the screen data
      for (const c of candleData) {
        store.appendScreenCandle(tf, c);
        if (tf === store.interval) {
          store.appendCandle(c);
        }
      }
    }

    // Refetch indicators for the current interval after backfill
    store.fetchIndicators();
  }

  private resetHeartbeat() {
    if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
    this.heartbeatTimer = setTimeout(() => {
      useTradingStore.getState().setDataFreshness("stale");
    }, HEARTBEAT_TIMEOUT);
  }

  private schedulePipelineReconnect() {
    if (this.destroyed) return;
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      useTradingStore.getState().setWsState("disconnected");
      this.startPolling();
      return;
    }

    // Exponential backoff with jitter to prevent thundering herd
    const base = Math.min(1000 * 2 ** this.reconnectAttempts, MAX_RECONNECT_DELAY);
    const jitter = Math.random() * Math.min(base * 0.3, 3000);
    const delay = base + jitter;

    this.reconnectAttempts++;
    useTradingStore.getState().setWsState("reconnecting");
    this.reconnectTimer = setTimeout(() => this.connectPipeline(), delay);
  }

  // ── REST polling fallback ───────────────────────────────────

  private maybeStartPolling() {
    if (this.destroyed || this.pollTimer) return;
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

    store.setWsState("polling");
    this.pollTimer = setInterval(() => {
      const s = useTradingStore.getState();
      if (s.pipelineWsConnected) {
        this.stopPolling();
        return;
      }
      s.fetchCandles();
      s.fetchIndicators();
    }, REST_POLL_INTERVAL);
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
      const token = typeof window !== 'undefined' ? localStorage.getItem('elder_token') : null;
      const tokenParam = token ? `?token=${token}` : '';
      this.marketWs = new WebSocket(`${WS_BASE}/ws/market${tokenParam}`);
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
    // Send stop_tracking before closing
    if (this.trackedSymbol && this.pipelineWs?.readyState === WebSocket.OPEN) {
      try {
        this.pipelineWs.send(JSON.stringify({
          action: "stop_tracking",
          symbol: this.trackedSymbol,
          exchange: this.trackedExchange,
        }));
      } catch { /* best effort */ }
    }
    this.pipelineWs?.close();
    this.marketWs?.close();
    this.pipelineWs = null;
    this.marketWs = null;
  }
}
