import { create } from "zustand";
import type {
  CandleData,
  IndicatorData,
  TripleScreenResult,
} from "@/lib/api";
import {
  fetchCandles,
  fetchIndicators,
  fetchPositions,
  fetchOrders,
  fetchTradingMode,
  fetchHealth,
} from "@/lib/api";

// ── Types ────────────────────────────────────────────────────

export interface PipelineSignal {
  symbol: string;
  action: string;
  grade: string;
  confidence: number;
  entry_price?: number;
  stop_price?: number;
  shares?: number;
  signal_id?: number;
  timestamp?: string;
}

export type DataFreshness = "live" | "stale" | "demo" | "disconnected" | "reconnecting";

export type WsState = "connecting" | "connected" | "reconnecting" | "disconnected" | "polling";

/** Incremental update descriptor — avoids full array diff in chart components */
export interface CandleUpdate {
  type: "append" | "update";
  candle: CandleData;
  impulseColor?: string | null;
}

/** Per-timeframe data slice for multi-screen live updates */
export interface ScreenSlice {
  candles: CandleData[];
  indicators: IndicatorData | null;
  runningBar: CandleData | null;
  lastUpdate: CandleUpdate | null;
  loading: boolean;
}

function emptyScreenSlice(): ScreenSlice {
  return { candles: [], indicators: null, runningBar: null, lastUpdate: null, loading: false };
}

interface TradingStore {
  // ── Asset ──
  symbol: string;
  exchange: string;
  interval: string;
  token: string;
  setAsset: (symbol: string, exchange: string) => void;
  setInterval: (interval: string) => void;
  setToken: (token: string) => void;

  // ── Market Data (main view) ──
  candles: CandleData[];
  indicators: IndicatorData | null;
  source: "live" | "demo" | null;
  loading: boolean;
  lastCandleTime: string | null;
  runningBar: CandleData | null;
  lastUpdate: CandleUpdate | null;
  fetchCandles: () => Promise<void>;
  fetchIndicators: () => Promise<void>;
  setIndicators: (data: IndicatorData) => void;
  appendCandle: (candle: CandleData) => void;
  updateRunningBar: (candle: CandleData) => void;

  // ── Multi-timeframe (Three Screen) ──
  screenData: Record<string, ScreenSlice>;
  setScreenCandles: (tf: string, candles: CandleData[]) => void;
  appendScreenCandle: (tf: string, candle: CandleData) => void;
  setScreenRunningBar: (tf: string, bar: CandleData | null) => void;
  setScreenIndicators: (tf: string, data: IndicatorData) => void;
  setScreenLoading: (tf: string, loading: boolean) => void;

  // ── Pipeline ──
  wsState: WsState;
  wsConnected: boolean;
  pipelineWsConnected: boolean;
  dataFreshness: DataFreshness;
  tradingMode: "PAPER" | "LIVE";
  apiOnline: boolean;
  brokerConnected: boolean;
  setWsState: (v: WsState) => void;
  setWsConnected: (v: boolean) => void;
  setPipelineWsConnected: (v: boolean) => void;
  setDataFreshness: (v: DataFreshness) => void;
  setTradingMode: (v: "PAPER" | "LIVE") => void;
  setApiOnline: (v: boolean) => void;
  setBrokerConnected: (v: boolean) => void;

  // ── Tick Activity ──
  tickCount: number;
  lastTickTime: number;
  incrementTick: () => void;

  // ── Signals ──
  signals: PipelineSignal[];
  activeSignal: PipelineSignal | null;
  tripleScreen: TripleScreenResult | null;
  addSignal: (signal: PipelineSignal) => void;
  setTripleScreen: (result: TripleScreenResult | null) => void;
  clearSignals: () => void;

  // ── Trade Events (toasts for non-signal events) ──
  tradeEvents: import("@/components/ui/TradeToast").TradeToastData[];
  addTradeEvent: (event: import("@/components/ui/TradeToast").TradeToastData) => void;

  // ── Command Center ──
  commandCenterAssets: import("@/lib/api").CommandCenterAsset[];
  setCommandCenterAssets: (assets: import("@/lib/api").CommandCenterAsset[]) => void;

  // ── Trades ──
  positions: any[];
  orders: any[];
  refreshPositions: () => Promise<void>;
  refreshOrders: () => Promise<void>;
}

// ── Store ─────────────────────────────────────────────────────

export const useTradingStore = create<TradingStore>((set, get) => ({
  // ── Asset ──
  symbol: "NIFTY",
  exchange: "NFO",
  interval: "1d",
  token: "",
  setAsset: (symbol, exchange) => {
    set({
      symbol, exchange,
      candles: [], indicators: null, loading: true,
      runningBar: null, lastUpdate: null,
      screenData: {},
      tripleScreen: null,
      activeSignal: null,
      signals: [],
    });
    setTimeout(() => {
      get().fetchCandles();
      get().fetchIndicators();
    }, 0);
  },
  setInterval: (interval) => {
    set({
      interval,
      candles: [], indicators: null, loading: true,
      runningBar: null, lastUpdate: null,
    });
    setTimeout(() => {
      get().fetchCandles();
      get().fetchIndicators();
    }, 0);
  },
  setToken: (token) => set({ token }),

  // ── Market Data ──
  candles: [],
  indicators: null,
  source: null,
  loading: false,
  lastCandleTime: null,
  runningBar: null,
  lastUpdate: null,

  fetchCandles: async () => {
    const { symbol, exchange, interval } = get();
    set({ loading: true });
    try {
      const res = await fetchCandles(symbol, exchange, interval);
      const candles = res.data || [];
      const lastTime = candles.length > 0 ? candles[candles.length - 1].timestamp : null;
      set({
        candles,
        source: res.source || null,
        lastCandleTime: lastTime,
        loading: false,
        runningBar: null,
        lastUpdate: null,
      });
    } catch {
      set({ loading: false });
    }
  },

  fetchIndicators: async () => {
    const { symbol, exchange, interval } = get();
    try {
      const res = await fetchIndicators(symbol, exchange, interval);
      set({ indicators: res.data || null });
    } catch {
      // Indicators are non-critical
    }
  },

  setIndicators: (data) => set({ indicators: data }),

  appendCandle: (candle) => {
    set((state) => ({
      candles: [...state.candles, candle],
      lastCandleTime: candle.timestamp,
      runningBar: null, // Clear running bar when a real candle arrives
      lastUpdate: { type: "append" as const, candle },
    }));
  },

  updateRunningBar: (candle) => {
    set({
      runningBar: candle,
      lastCandleTime: candle.timestamp,
    });
  },

  // ── Multi-timeframe (Three Screen) ──
  screenData: {},

  setScreenCandles: (tf, candles) => {
    set((state) => ({
      screenData: {
        ...state.screenData,
        [tf]: {
          ...(state.screenData[tf] || emptyScreenSlice()),
          candles,
          loading: false,
          lastUpdate: null,
          runningBar: null,
        },
      },
    }));
  },

  appendScreenCandle: (tf, candle) => {
    set((state) => {
      const slice = state.screenData[tf] || emptyScreenSlice();
      return {
        screenData: {
          ...state.screenData,
          [tf]: {
            ...slice,
            candles: [...slice.candles, candle],
            runningBar: null,
            lastUpdate: { type: "append" as const, candle },
          },
        },
      };
    });
  },

  setScreenRunningBar: (tf, bar) => {
    set((state) => {
      const slice = state.screenData[tf] || emptyScreenSlice();
      return {
        screenData: {
          ...state.screenData,
          [tf]: { ...slice, runningBar: bar },
        },
      };
    });
  },

  setScreenIndicators: (tf, data) => {
    set((state) => {
      const slice = state.screenData[tf] || emptyScreenSlice();
      return {
        screenData: {
          ...state.screenData,
          [tf]: { ...slice, indicators: data },
        },
      };
    });
  },

  setScreenLoading: (tf, loading) => {
    set((state) => {
      const slice = state.screenData[tf] || emptyScreenSlice();
      return {
        screenData: {
          ...state.screenData,
          [tf]: { ...slice, loading },
        },
      };
    });
  },

  // ── Pipeline ──
  wsState: "disconnected",
  wsConnected: false,
  pipelineWsConnected: false,
  dataFreshness: "disconnected",
  tradingMode: "PAPER",
  apiOnline: false,
  brokerConnected: false,
  setWsState: (v) => set({ wsState: v }),
  setWsConnected: (v) => set({ wsConnected: v }),
  setPipelineWsConnected: (v) => set({ pipelineWsConnected: v }),
  setDataFreshness: (v) => set({ dataFreshness: v }),
  setTradingMode: (v) => set({ tradingMode: v }),
  setApiOnline: (v) => set({ apiOnline: v }),
  setBrokerConnected: (v) => set({ brokerConnected: v }),

  // ── Tick Activity ──
  tickCount: 0,
  lastTickTime: 0,
  incrementTick: () => set((state) => ({ tickCount: state.tickCount + 1, lastTickTime: Date.now() })),

  // ── Signals ──
  signals: [],
  activeSignal: null,
  tripleScreen: null,
  addSignal: (signal) => {
    set((state) => ({
      signals: [signal, ...state.signals].slice(0, 50),
      activeSignal: signal,
    }));
  },
  setTripleScreen: (result) => set({ tripleScreen: result }),
  clearSignals: () => set({ signals: [], activeSignal: null }),

  // ── Trade Events ──
  tradeEvents: [],
  addTradeEvent: (event) => {
    set((state) => ({
      tradeEvents: [event, ...state.tradeEvents].slice(0, 20),
    }));
  },

  // ── Command Center ──
  commandCenterAssets: [],
  setCommandCenterAssets: (assets) => set({ commandCenterAssets: assets }),

  // ── Trades ──
  positions: [],
  orders: [],
  refreshPositions: async () => {
    try {
      const res = await fetchPositions();
      set({ positions: res.data || [] });
    } catch {
      // Positions refresh failed — keep stale data
    }
  },
  refreshOrders: async () => {
    try {
      const res = await fetchOrders();
      set({ orders: res.data || [] });
    } catch {
      // Orders refresh failed — keep stale data
    }
  },
}));
