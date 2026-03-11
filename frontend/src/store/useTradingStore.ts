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

export type DataFreshness = "live" | "stale" | "demo" | "disconnected";

interface TradingStore {
  // ── Asset ──
  symbol: string;
  exchange: string;
  interval: string;
  token: string;
  setAsset: (symbol: string, exchange: string) => void;
  setInterval: (interval: string) => void;
  setToken: (token: string) => void;

  // ── Market Data ──
  candles: CandleData[];
  indicators: IndicatorData | null;
  source: "live" | "demo" | null;
  loading: boolean;
  lastCandleTime: string | null;
  fetchCandles: () => Promise<void>;
  fetchIndicators: () => Promise<void>;
  appendCandle: (candle: CandleData) => void;
  updateLastCandle: (candle: CandleData) => void;

  // ── Pipeline ──
  wsConnected: boolean;
  pipelineWsConnected: boolean;
  dataFreshness: DataFreshness;
  tradingMode: "PAPER" | "LIVE";
  apiOnline: boolean;
  brokerConnected: boolean;
  setWsConnected: (v: boolean) => void;
  setPipelineWsConnected: (v: boolean) => void;
  setDataFreshness: (v: DataFreshness) => void;
  setTradingMode: (v: "PAPER" | "LIVE") => void;
  setApiOnline: (v: boolean) => void;
  setBrokerConnected: (v: boolean) => void;

  // ── Signals ──
  signals: PipelineSignal[];
  activeSignal: PipelineSignal | null;
  tripleScreen: TripleScreenResult | null;
  addSignal: (signal: PipelineSignal) => void;
  setTripleScreen: (result: TripleScreenResult | null) => void;
  clearSignals: () => void;

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
    set({ symbol, exchange, candles: [], indicators: null, loading: true });
    // Fetch new data after asset change
    setTimeout(() => {
      get().fetchCandles();
      get().fetchIndicators();
    }, 0);
  },
  setInterval: (interval) => {
    set({ interval, candles: [], indicators: null, loading: true });
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

  appendCandle: (candle) => {
    set((state) => ({
      candles: [...state.candles, candle],
      lastCandleTime: candle.timestamp,
    }));
  },

  updateLastCandle: (candle) => {
    set((state) => {
      if (state.candles.length === 0) return { candles: [candle] };
      const updated = [...state.candles];
      const last = updated[updated.length - 1];
      if (last.timestamp === candle.timestamp) {
        updated[updated.length - 1] = candle;
      } else {
        updated.push(candle);
      }
      return { candles: updated, lastCandleTime: candle.timestamp };
    });
  },

  // ── Pipeline ──
  wsConnected: false,
  pipelineWsConnected: false,
  dataFreshness: "disconnected",
  tradingMode: "PAPER",
  apiOnline: false,
  brokerConnected: false,
  setWsConnected: (v) => set({ wsConnected: v }),
  setPipelineWsConnected: (v) => set({ pipelineWsConnected: v }),
  setDataFreshness: (v) => set({ dataFreshness: v }),
  setTradingMode: (v) => set({ tradingMode: v }),
  setApiOnline: (v) => set({ apiOnline: v }),
  setBrokerConnected: (v) => set({ brokerConnected: v }),

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
