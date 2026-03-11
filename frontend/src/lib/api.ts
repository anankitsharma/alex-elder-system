const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Resilient fetch with timeout and retry ──────────────────
const DEFAULT_TIMEOUT = 30000; // 30s — Angel One API can be slow
const MAX_RETRIES = 2;
const RETRY_DELAY = 1000; // 1s

async function apiFetch<T>(
  path: string,
  init?: RequestInit & { retries?: number; timeout?: number }
): Promise<T> {
  const { retries = MAX_RETRIES, timeout = DEFAULT_TIMEOUT, ...fetchInit } =
    init || {};

  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);

    try {
      const res = await fetch(`${BASE}${path}`, {
        ...fetchInit,
        signal: controller.signal,
        headers: { "Content-Type": "application/json", ...fetchInit?.headers },
      });

      clearTimeout(timer);

      if (!res.ok) {
        // Don't retry client errors (4xx)
        if (res.status >= 400 && res.status < 500) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || `API ${res.status}: ${res.statusText}`);
        }
        throw new Error(`API ${res.status}: ${res.statusText}`);
      }

      return (await res.json()) as T;
    } catch (err: any) {
      clearTimeout(timer);
      lastError = err;

      // Don't retry aborts (timeout) or client errors
      if (err.name === "AbortError") {
        lastError = new Error("Request timed out");
        break;
      }
      if (err.message?.startsWith("API 4")) break;

      // Wait before retry
      if (attempt < retries) {
        await new Promise((r) => setTimeout(r, RETRY_DELAY * (attempt + 1)));
      }
    }
  }

  throw lastError || new Error("Request failed");
}

// ── Chart data ──────────────────────────────────────────────
export interface CandleData {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandleResponse {
  data: CandleData[];
  symbol: string;
  exchange: string;
  interval: string;
  count: number;
  error?: string;
  source?: "live" | "demo";
}

export function fetchCandles(
  symbol: string,
  exchange = "NSE",
  interval = "1d",
  days = 365
) {
  return apiFetch<CandleResponse>(
    `/api/charts/candles?symbol=${encodeURIComponent(symbol)}&exchange=${exchange}&interval=${interval}&days=${days}`
  );
}

export function fetchWeekly(symbol: string, exchange = "NSE", days = 730) {
  return apiFetch<CandleResponse>(
    `/api/charts/weekly?symbol=${encodeURIComponent(symbol)}&exchange=${exchange}&days=${days}`
  );
}

// ── Trading ─────────────────────────────────────────────────
export interface TradingMode {
  mode: "PAPER" | "LIVE";
}

export function fetchTradingMode() {
  return apiFetch<TradingMode>("/api/trading/mode");
}

export interface BrokerResponse {
  data: any;
  status?: boolean;
  message?: string;
}

export function fetchPositions() {
  return apiFetch<BrokerResponse>("/api/trading/positions");
}

export function fetchOrders() {
  return apiFetch<BrokerResponse>("/api/trading/orders");
}

export function fetchHoldings() {
  return apiFetch<BrokerResponse>("/api/trading/holdings");
}

export function fetchFunds() {
  return apiFetch<BrokerResponse>("/api/trading/funds");
}

export function fetchProfile() {
  return apiFetch<BrokerResponse>("/api/trading/profile");
}

export interface OrderRequest {
  symbol: string;
  token: string;
  exchange: string;
  direction: "BUY" | "SELL";
  order_type: "MARKET" | "LIMIT" | "SL" | "SL-M";
  quantity: number;
  price: number;
  trigger_price: number;
  product_type: "DELIVERY" | "INTRADAY";
}

export function placeOrder(order: OrderRequest) {
  return apiFetch<{ status: boolean; message: string; order?: any }>(
    "/api/trading/order",
    {
      method: "POST",
      body: JSON.stringify(order),
      retries: 0, // Never retry order placement
    }
  );
}

export function cancelOrder(orderId: string) {
  return apiFetch<{ status: boolean; message: string }>(
    `/api/trading/order/${orderId}`,
    { method: "DELETE", retries: 0 }
  );
}

export function refreshSession() {
  return apiFetch<{ status: boolean; message: string }>(
    "/api/trading/session/refresh",
    { method: "POST", retries: 0 }
  );
}

export function resetPaperAccount() {
  return apiFetch<{ status: boolean; message: string }>(
    "/api/trading/paper/reset",
    { method: "POST", retries: 0 }
  );
}

// ── Scanner ─────────────────────────────────────────────────
export interface InstrumentData {
  token: string;
  symbol: string;
  display_symbol: string;
  name: string;
  exch_seg: string;
  lotsize: number;
  tick_size: number;
}

export interface InstrumentsResponse {
  instruments: InstrumentData[];
  count: number;
  exchange: string;
}

export function fetchInstruments(exchange = "NSE", search = "", limit = 50) {
  return apiFetch<InstrumentsResponse>(
    `/api/scanner/instruments?exchange=${exchange}&search=${encodeURIComponent(search)}&limit=${limit}`
  );
}

// ── Indicators ─────────────────────────────────────────────
export interface IndicatorData {
  timestamps: string[];
  ema13: (number | null)[];
  ema22: (number | null)[];
  macd_line: (number | null)[];
  macd_signal: (number | null)[];
  macd_histogram: (number | null)[];
  force_index: (number | null)[];
  force_index_2: (number | null)[];
  impulse_color: (string | null)[];
  impulse_signal: (string | null)[];
  safezone_long: (number | null)[];
  safezone_short: (number | null)[];
  elder_ray_bull: (number | null)[];
  elder_ray_bear: (number | null)[];
  value_zone_fast: (number | null)[];
  value_zone_slow: (number | null)[];
  auto_envelope_upper: (number | null)[];
  auto_envelope_lower: (number | null)[];
  auto_envelope_ema: (number | null)[];
  thermometer_raw: (number | null)[];
  thermometer_smoothed: (number | null)[];
  macd_divergence_signal: (number | null)[];
}

export interface IndicatorResponse {
  symbol: string;
  exchange: string;
  interval: string;
  count: number;
  data: IndicatorData;
  error?: string;
}

export function fetchIndicators(
  symbol: string,
  exchange = "NSE",
  interval = "1d",
  days = 365,
  screen?: number
) {
  let url = `/api/indicators/compute?symbol=${encodeURIComponent(symbol)}&exchange=${exchange}&interval=${interval}&days=${days}`;
  if (screen != null) url += `&screen=${screen}`;
  return apiFetch<IndicatorResponse>(url);
}

// ── Health ──────────────────────────────────────────────────
export interface HealthResponse {
  status: string;
  trading_mode: string;
  risk_per_trade: string;
  portfolio_risk_limit: string;
  min_signal_score: number;
}

export function fetchHealth() {
  return apiFetch<HealthResponse>("/api/health");
}

// ── Strategy & Risk ─────────────────────────────────────────
export interface PositionSizeResult {
  shares: number;
  lots: number | null;
  lot_size: number;
  risk_amount: number;
  risk_pct: number;
  risk_per_share: number;
  max_risk_amount: number;
  entry_price: number;
  stop_price: number;
  position_value: number;
  actual_risk_pct: number;
  account_equity: number;
  is_valid: boolean;
  reason?: string;
}

export function calculatePositionSize(
  entryPrice: number,
  stopPrice: number,
  accountEquity: number,
  lotSize = 1,
  maxRiskPct?: number
) {
  return apiFetch<PositionSizeResult>("/api/strategy/position-size", {
    method: "POST",
    body: JSON.stringify({
      entry_price: entryPrice,
      stop_price: stopPrice,
      account_equity: accountEquity,
      lot_size: lotSize,
      max_risk_pct: maxRiskPct,
    }),
    retries: 0,
  });
}

export interface CircuitBreakerStatus {
  is_allowed: boolean;
  is_halted: boolean;
  halt_reason: string | null;
  month_start_equity: number;
  realized_losses: number;
  open_risk: number;
  total_exposure: number;
  max_allowed: number;
  exposure_pct: number;
  max_portfolio_risk_pct: number;
  remaining_budget: number;
  current_month: string;
  open_positions_count: number;
}

export function fetchCircuitBreakerStatus() {
  return apiFetch<CircuitBreakerStatus>("/api/strategy/circuit-breaker");
}

export interface RiskSummary {
  two_percent_rule: { max_risk_per_trade_pct: number; description: string };
  six_percent_rule: CircuitBreakerStatus;
  trading_mode: string;
  min_signal_score: number;
}

export function fetchRiskSummary() {
  return apiFetch<RiskSummary>("/api/strategy/risk-summary");
}

export interface TripleScreenResult {
  screen1: {
    tide: string;
    macd_histogram_slope: number;
    impulse_signal: string;
    impulse_confirms: boolean;
    ema_trend: string;
  };
  screen2: {
    signal: string;
    force_index_2: number;
    elder_ray_bear: number;
    elder_ray_bull: number;
    impulse_signal: string;
    bear_trend: string;
    bull_trend: string;
    reasons: string[];
  };
  screen3: {
    entry_type: string;
    entry_price?: number;
    stop_price?: number;
    safezone_long?: number;
    safezone_short?: number;
  };
  recommendation: {
    action: string;
    reason: string;
    confidence: number;
    entry_type?: string;
    entry_price?: number;
    stop_price?: number;
  };
  grade: string;
  validation: {
    is_valid: boolean;
    warnings: string[];
    blocks: string[];
  };
}

export interface ScreenConfig {
  symbol: string;
  exchange: string;
  asset_class: string;
  screens: {
    [key: string]: {
      label: string;
      timeframe: string;
      indicators: string[];
    };
  };
}

export function analyzeTripleScreen(data: Record<string, unknown>) {
  return apiFetch<TripleScreenResult>("/api/strategy/triple-screen", {
    method: "POST",
    body: JSON.stringify(data),
    retries: 0,
  });
}

export function fetchScreenConfig(symbol: string, exchange = "NSE") {
  return apiFetch<ScreenConfig>(
    `/api/strategy/screen-config?symbol=${encodeURIComponent(symbol)}&exchange=${exchange}`
  );
}

// ── Settings ────────────────────────────────────────────────
export interface WatchlistEntry {
  symbol: string;
  exchange: string;
}

export interface TimeframeConfig {
  screen1: string;
  screen2: string;
  screen3: string;
}

export interface RiskSettings {
  max_risk_per_trade_pct: number;
  max_portfolio_risk_pct: number;
  min_signal_score: number;
}

export interface DisplaySettings {
  default_symbol: string;
  default_exchange: string;
  default_interval: string;
  show_volume: boolean;
  show_macd: boolean;
  show_force_index: boolean;
  show_elder_ray: boolean;
}

export interface AllSettings {
  watchlist: WatchlistEntry[];
  timeframes: Record<string, TimeframeConfig>;
  risk: RiskSettings;
  display: DisplaySettings;
}

export function fetchAllSettings() {
  return apiFetch<AllSettings>("/api/settings");
}

export function updateSetting(key: string, value: unknown) {
  return apiFetch<{ status: boolean; key: string; value: unknown }>(
    `/api/settings/${key}`,
    { method: "PUT", body: JSON.stringify({ value }), retries: 0 }
  );
}

export function addToWatchlist(symbol: string, exchange = "NSE") {
  return apiFetch<{ status: boolean; watchlist: WatchlistEntry[] }>(
    "/api/settings/watchlist/add",
    { method: "POST", body: JSON.stringify({ symbol, exchange }), retries: 0 }
  );
}

export function removeFromWatchlist(symbol: string, exchange = "NSE") {
  return apiFetch<{ status: boolean; watchlist: WatchlistEntry[] }>(
    "/api/settings/watchlist/remove",
    { method: "POST", body: JSON.stringify({ symbol, exchange }), retries: 0 }
  );
}

// ── Pipeline ────────────────────────────────────────────────

export interface PipelineStatus {
  active_sessions: number;
  sessions: Record<string, {
    symbol: string;
    exchange: string;
    token: string;
    active: boolean;
    candle_counts: Record<string, number>;
    source: string;
    has_analysis: boolean;
    latest_grade: string | null;
    latest_action: string | null;
  }>;
}

export function startPipeline(symbol: string, exchange = "NSE") {
  return apiFetch<{ status: boolean; message: string; session?: unknown }>(
    "/api/strategy/pipeline/start",
    {
      method: "POST",
      body: JSON.stringify({ symbol, exchange }),
      retries: 0,
    }
  );
}

export function stopPipeline(symbol: string, exchange = "NSE") {
  return apiFetch<{ status: boolean; message: string }>(
    "/api/strategy/pipeline/stop",
    {
      method: "POST",
      body: JSON.stringify({ symbol, exchange }),
      retries: 0,
    }
  );
}

export function fetchPipelineStatus() {
  return apiFetch<PipelineStatus>("/api/strategy/pipeline/status");
}

export function fetchPipelineSignals(limit = 20) {
  return apiFetch<{ signals: unknown[] }>(
    `/api/strategy/pipeline/signals?limit=${limit}`
  );
}

export function fetchPipelineAnalysis(symbol: string, exchange = "NSE") {
  return apiFetch<{ symbol: string; exchange: string; analysis: TripleScreenResult | null }>(
    `/api/strategy/pipeline/analysis/${encodeURIComponent(symbol)}?exchange=${exchange}`
  );
}

// ── WebSocket ───────────────────────────────────────────────
export function createMarketSocket(): WebSocket {
  const wsUrl = BASE.replace(/^http/, "ws") + "/ws/market";
  return new WebSocket(wsUrl);
}

export function createPipelineSocket(): WebSocket {
  const wsUrl = BASE.replace(/^http/, "ws") + "/ws/pipeline";
  return new WebSocket(wsUrl);
}
