"use client";

import { useState, useEffect, useCallback } from "react";
import {
  fetchFunds,
  fetchPositions,
  fetchOrders,
  fetchRiskSummary,
  fetchHealth,
  analyzeTripleScreen,
  type CandleData,
  type IndicatorData,
  type TripleScreenResult,
  type RiskSummary,
  type HealthResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useTradingStore } from "@/store/useTradingStore";
import CommandCenterGrid from "./CommandCenterGrid";
import {
  Wallet,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Shield,
  Activity,
  RefreshCw,
  Loader2,
  Wifi,
  WifiOff,
  Server,
  ShieldCheck,
  ShieldAlert,
  ChevronRight,
  CircleDot,
} from "lucide-react";

/* ── types ─────────────────────────────────────────── */

interface Props {
  symbol: string;
  exchange: string;
  wsConnected: boolean;
  candles: CandleData[];
  indicators: IndicatorData | null;
  onNavigate: (view: string) => void;
  onAssetSelect?: (symbol: string, exchange: string) => void;
}

/* ── helpers ───────────────────────────────────────── */

function inr(n: number | string | null | undefined): string {
  const v = Number(n);
  if (isNaN(v)) return "—";
  return v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function inr2(n: number | string | null | undefined): string {
  const v = Number(n);
  if (isNaN(v)) return "—";
  return v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/* ── stat card ─────────────────────────────────────── */

function Stat({
  label,
  icon: Icon,
  value,
  sub,
  accent,
  delay,
}: {
  label: string;
  icon: typeof Wallet;
  value: React.ReactNode;
  sub?: React.ReactNode;
  accent: string;
  delay: number;
}) {
  return (
    <div
      className="rounded-lg bg-surface border border-border p-3.5 opacity-0 card-elevated"
      style={{
        borderTop: `2px solid ${accent}`,
        animation: `fade-up 0.4s ease-out ${delay}ms forwards`,
      }}
    >
      <div className="flex items-center gap-1.5 text-[10px] text-muted mb-2.5">
        <Icon className="w-3 h-3 shrink-0" />
        <span className="truncate">{label}</span>
      </div>
      <div className="text-[18px] font-mono font-semibold text-foreground leading-none tracking-tight tabular-nums">
        {value}
      </div>
      {sub && <div className="mt-2 text-[10px]">{sub}</div>}
    </div>
  );
}

/* ── section wrapper ───────────────────────────────── */

function Section({
  title,
  action,
  onAction,
  children,
  delay,
}: {
  title: string;
  action?: string;
  onAction?: () => void;
  children: React.ReactNode;
  delay: number;
}) {
  return (
    <div
      className="rounded-lg bg-surface border border-border overflow-hidden opacity-0 card-elevated"
      style={{ animation: `fade-up 0.4s ease-out ${delay}ms forwards` }}
    >
      <div className="flex items-center justify-between px-3.5 py-2 border-b border-border">
        <span className="text-[11px] font-semibold text-foreground tracking-tight">{title}</span>
        {action && (
          <button
            onClick={onAction}
            className="flex items-center gap-0.5 text-[10px] text-accent hover:text-accent-hover transition-colors"
          >
            {action}
            <ChevronRight className="w-3 h-3" />
          </button>
        )}
      </div>
      {children}
    </div>
  );
}

/* ── component ─────────────────────────────────────── */

export default function DashboardView({
  symbol,
  exchange,
  wsConnected,
  candles,
  indicators,
  onNavigate,
  onAssetSelect,
}: Props) {
  /* command center from store */
  const commandCenterAssets = useTradingStore((s) => s.commandCenterAssets);

  /* state */
  const [funds, setFunds] = useState<Record<string, unknown> | null>(null);
  const [positions, setPositions] = useState<Record<string, unknown>[]>([]);
  const [orders, setOrders] = useState<Record<string, unknown>[]>([]);
  const [risk, setRisk] = useState<RiskSummary | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [signal, setSignal] = useState<TripleScreenResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  /* fetch summary data */
  const load = useCallback(async () => {
    const [f, p, o, r, h] = await Promise.allSettled([
      fetchFunds(),
      fetchPositions(),
      fetchOrders(),
      fetchRiskSummary(),
      fetchHealth(),
    ]);
    setFunds(f.status === "fulfilled" ? (f.value?.data as Record<string, unknown> ?? null) : null);
    setPositions(p.status === "fulfilled" ? (Array.isArray(p.value?.data) ? p.value.data as Record<string, unknown>[] : []) : []);
    setOrders(o.status === "fulfilled" ? (Array.isArray(o.value?.data) ? o.value.data as Record<string, unknown>[] : []) : []);
    setRisk(r.status === "fulfilled" ? r.value : null);
    setHealth(h.status === "fulfilled" ? h.value : null);
  }, []);

  useEffect(() => { load().finally(() => setLoading(false)); }, [load]);

  /* signal analysis */
  useEffect(() => {
    if (!candles.length || !indicators) return;
    analyzeTripleScreen({
      candles: candles.map((c) => ({
        open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume,
      })),
      indicators: {
        ema13: indicators.ema13,
        macd_histogram: indicators.macd_histogram,
        force_index_2: indicators.force_index_2,
        elder_ray_bull: indicators.elder_ray_bull,
        elder_ray_bear: indicators.elder_ray_bear,
        impulse_signal: indicators.impulse_signal,
        value_zone_fast: indicators.value_zone_fast,
        value_zone_slow: indicators.value_zone_slow,
        safezone_long: indicators.safezone_long,
        safezone_short: indicators.safezone_short,
      },
    })
      .then(setSignal)
      .catch(() => setSignal(null));
  }, [candles, indicators]);

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  /* computed */
  const totalPnl = positions.reduce((s, p) => s + (parseFloat(String(p.pnl ?? 0)) || 0), 0);
  const activePos = positions.filter((p) => parseInt(String(p.netqty ?? 0)) !== 0);
  const pendingOrd = orders.filter((o) => o.status === "open" || o.status === "pending" || o.status === "trigger pending");
  const balance = Number(funds?.availablecash ?? funds?.net ?? 0);
  const margin = Number(funds?.utilisedmargin ?? 0);
  const riskPct = risk?.six_percent_rule?.exposure_pct ?? 0;
  const riskOk = (risk?.six_percent_rule?.is_allowed ?? true) && !(risk?.six_percent_rule?.is_halted);
  const mode = health?.trading_mode ?? risk?.trading_mode ?? "PAPER";

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-5 h-5 text-muted animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto dashboard-grid">
      {/* ── header ──────────────────────────────────── */}
      <div className="sticky top-0 z-20 backdrop-blur-md bg-background/75 border-b border-border">
        <div className="flex items-center justify-between px-6 h-11">
          <div className="flex items-center gap-3">
            <h1 className="text-[13px] font-semibold text-foreground tracking-tight">Overview</h1>
            <span
              className={cn(
                "px-2 py-0.5 rounded text-[9px] font-mono font-bold tracking-wider",
                mode === "PAPER"
                  ? "bg-amber/8 text-amber border border-amber/15"
                  : "bg-green/8 text-green border border-green/15"
              )}
            >
              {mode}
            </span>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-3 text-[10px]">
              <span className="flex items-center gap-1.5">
                <span className={cn("w-1.5 h-1.5 rounded-full", health ? "bg-green animate-pulse-dot" : "bg-red")} />
                <span className="text-muted">API</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className={cn("w-1.5 h-1.5 rounded-full", wsConnected ? "bg-green animate-pulse-dot" : "bg-red")} />
                <span className="text-muted">Feed</span>
              </span>
            </div>
            <button
              onClick={refresh}
              disabled={refreshing}
              className="p-1.5 rounded-md hover:bg-surface-2 text-muted hover:text-foreground transition-colors disabled:opacity-30"
              title="Refresh all data"
            >
              <RefreshCw className={cn("w-3.5 h-3.5", refreshing && "animate-spin")} />
            </button>
          </div>
        </div>
      </div>

      {/* ── content ─────────────────────────────────── */}
      <div className="p-5 space-y-4 max-w-[1400px] mx-auto">

        {/* ── stat cards ────────────────────────────── */}
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
          <Stat
            label="Available Balance"
            icon={Wallet}
            value={<>₹{inr(balance)}</>}
            accent="var(--color-accent)"
            delay={0}
          />
          <Stat
            label="Day P&L"
            icon={totalPnl >= 0 ? TrendingUp : TrendingDown}
            value={
              <span className={totalPnl >= 0 ? "text-green" : "text-red"}>
                {totalPnl >= 0 ? "+" : ""}₹{inr(Math.abs(totalPnl))}
              </span>
            }
            accent={totalPnl >= 0 ? "var(--color-green)" : "var(--color-red)"}
            delay={40}
          />
          <Stat
            label="Used Margin"
            icon={BarChart3}
            value={<>₹{inr(margin)}</>}
            sub={
              balance + margin > 0 ? (
                <span className="text-muted">{((margin / (balance + margin)) * 100).toFixed(0)}% utilized</span>
              ) : undefined
            }
            accent="var(--color-amber)"
            delay={80}
          />
          <Stat
            label="Active Trades"
            icon={Activity}
            value={String(activePos.length)}
            sub={
              pendingOrd.length > 0 ? (
                <span className="text-muted">{pendingOrd.length} pending</span>
              ) : undefined
            }
            accent="var(--color-blue)"
            delay={120}
          />
          <Stat
            label="Risk Exposure"
            icon={Shield}
            value={
              <span className={riskOk ? "text-green" : "text-red"}>
                {riskPct.toFixed(1)}%
              </span>
            }
            sub={
              <div>
                <div className="h-1 w-full bg-track rounded-full overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all duration-500",
                      riskPct < 3 ? "bg-green" : riskPct < 5 ? "bg-amber" : "bg-red"
                    )}
                    style={{ width: `${Math.min(100, (riskPct / 6) * 100)}%` }}
                  />
                </div>
                <span className="text-muted text-[9px]">of 6% monthly limit</span>
              </div>
            }
            accent={riskOk ? "var(--color-green)" : "var(--color-red)"}
            delay={160}
          />
        </div>

        {/* ── command center ─────────────────────────── */}
        <Section title="Command Center — All Assets" action="View Charts" onAction={() => onNavigate("charts")} delay={200}>
          <CommandCenterGrid
            assets={commandCenterAssets}
            onSelectAsset={(sym, exch) => { if (onAssetSelect) onAssetSelect(sym, exch); }}
          />
        </Section>

        {/* ── positions + orders ────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <Section title="Open Positions" action="All Trades" onAction={() => onNavigate("trades")} delay={220}>
            {activePos.length === 0 ? (
              <div className="py-8 text-center text-[11px] text-muted">No open positions</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="text-[10px] text-muted border-b border-border/50">
                      <th className="text-left font-normal px-3.5 py-1.5">Symbol</th>
                      <th className="text-right font-normal px-3.5 py-1.5">Qty</th>
                      <th className="text-right font-normal px-3.5 py-1.5">LTP</th>
                      <th className="text-right font-normal px-3.5 py-1.5">P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activePos.slice(0, 6).map((p, i) => {
                      const pnl = parseFloat(String(p.pnl ?? 0));
                      const qty = parseInt(String(p.netqty ?? 0));
                      return (
                        <tr key={i} className="border-b border-border/30 last:border-0 hover:bg-surface-2/40 transition-colors">
                          <td className="px-3.5 py-2 font-medium text-foreground">{String(p.tradingsymbol)}</td>
                          <td className={cn("px-3.5 py-2 text-right font-mono", qty > 0 ? "text-green" : "text-red")}>
                            {qty > 0 ? "+" : ""}{qty}
                          </td>
                          <td className="px-3.5 py-2 text-right font-mono text-foreground">
                            {inr2(p.ltp as number)}
                          </td>
                          <td className={cn("px-3.5 py-2 text-right font-mono", pnl >= 0 ? "text-green" : "text-red")}>
                            {pnl >= 0 ? "+" : ""}₹{inr(Math.abs(pnl))}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {activePos.length > 6 && (
                  <div className="text-center py-1.5 text-[10px] text-muted">
                    +{activePos.length - 6} more positions
                  </div>
                )}
                {/* Total P&L row */}
                <div className="flex items-center justify-between px-3.5 py-2 border-t border-border bg-surface-2/30">
                  <span className="text-[10px] text-muted font-medium">Total P&L</span>
                  <span className={cn("text-[11px] font-mono font-semibold", totalPnl >= 0 ? "text-green" : "text-red")}>
                    {totalPnl >= 0 ? "+" : ""}₹{inr(Math.abs(totalPnl))}
                  </span>
                </div>
              </div>
            )}
          </Section>

          <Section title="Recent Orders" action="Order History" onAction={() => onNavigate("trades")} delay={260}>
            {orders.length === 0 ? (
              <div className="py-8 text-center text-[11px] text-muted">No recent orders</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="text-[10px] text-muted border-b border-border/50">
                      <th className="text-left font-normal px-3.5 py-1.5">Symbol</th>
                      <th className="text-left font-normal px-3.5 py-1.5">Side</th>
                      <th className="text-right font-normal px-3.5 py-1.5">Qty</th>
                      <th className="text-right font-normal px-3.5 py-1.5">Price</th>
                      <th className="text-right font-normal px-3.5 py-1.5">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.slice(0, 6).map((o, i) => (
                      <tr key={i} className="border-b border-border/30 last:border-0 hover:bg-surface-2/40 transition-colors">
                        <td className="px-3.5 py-2 font-medium text-foreground">{String(o.tradingsymbol)}</td>
                        <td className={cn("px-3.5 py-2 font-medium", o.transactiontype === "BUY" ? "text-green" : "text-red")}>
                          {String(o.transactiontype)}
                        </td>
                        <td className="px-3.5 py-2 text-right font-mono text-foreground">{String(o.quantity)}</td>
                        <td className="px-3.5 py-2 text-right font-mono text-foreground">{inr2(o.price as number)}</td>
                        <td className="px-3.5 py-2 text-right">
                          <span
                            className={cn(
                              "inline-block px-1.5 py-0.5 rounded text-[9px] font-medium",
                              o.status === "complete"  ? "bg-green/10 text-green" :
                              o.status === "rejected"  ? "bg-red/10 text-red" :
                              o.status === "cancelled" ? "bg-surface-2 text-muted" :
                              "bg-amber/10 text-amber"
                            )}
                          >
                            {String(o.status)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </div>

        {/* ── signal + system status ────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-3">
          {/* Signal — wider */}
          <div className="lg:col-span-3">
            <Section title={`Market Signal — ${symbol}`} action="Full Analysis" onAction={() => onNavigate("signals")} delay={320}>
              {!signal ? (
                <div className="py-8 text-center text-[11px] text-muted">
                  {candles.length === 0 ? "Waiting for market data..." : (
                    <span className="flex items-center justify-center gap-2">
                      <Loader2 className="w-3 h-3 animate-spin" /> Analyzing...
                    </span>
                  )}
                </div>
              ) : (
                <div className="p-3.5 space-y-3">
                  {/* Action + Grade + Confidence */}
                  <div className="flex items-center gap-2.5">
                    <span
                      className={cn(
                        "px-3 py-1.5 rounded text-[12px] font-bold uppercase tracking-wide",
                        signal.recommendation.action === "BUY"  ? "bg-green/12 text-green border border-green/15" :
                        signal.recommendation.action === "SELL" ? "bg-red/12 text-red border border-red/15" :
                        "bg-surface-2 text-muted border border-border"
                      )}
                    >
                      {signal.recommendation.action}
                    </span>
                    <span
                      className={cn(
                        "px-2 py-1 rounded border text-[10px] font-bold",
                        signal.grade === "A" ? "bg-green/8 text-green border-green/15" :
                        signal.grade === "B" ? "bg-green/6 text-green border-green/12" :
                        signal.grade === "C" ? "bg-amber/8 text-amber border-amber/15" :
                        "bg-red/8 text-red border-red/15"
                      )}
                    >
                      Grade {signal.grade}
                    </span>
                    <div className="flex-1" />
                    <span className="text-[12px] font-mono font-semibold text-muted tabular-nums">
                      {signal.recommendation.confidence}%
                    </span>
                  </div>

                  {/* Confidence bar */}
                  <div className="h-1 w-full bg-track rounded-full overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all duration-700",
                        signal.recommendation.confidence >= 70 ? "bg-green" :
                        signal.recommendation.confidence >= 40 ? "bg-amber" : "bg-red"
                      )}
                      style={{ width: `${signal.recommendation.confidence}%` }}
                    />
                  </div>

                  {/* Screen details */}
                  <div className="grid grid-cols-3 gap-3 text-[10px]">
                    <div className="bg-surface-2/40 rounded p-2">
                      <span className="text-muted block mb-1">Screen 1 — Tide</span>
                      <span
                        className={cn(
                          "font-semibold text-[11px]",
                          signal.screen1.tide === "BULLISH" ? "text-green" :
                          signal.screen1.tide === "BEARISH" ? "text-red" : "text-muted"
                        )}
                      >
                        {signal.screen1.tide}
                      </span>
                    </div>
                    <div className="bg-surface-2/40 rounded p-2">
                      <span className="text-muted block mb-1">Entry</span>
                      <span className="font-mono font-medium text-foreground text-[11px]">
                        {signal.screen3.entry_price != null
                          ? `₹${signal.screen3.entry_price.toFixed(2)}`
                          : "—"}
                      </span>
                    </div>
                    <div className="bg-surface-2/40 rounded p-2">
                      <span className="text-muted block mb-1">Stop</span>
                      <span className="font-mono font-medium text-red text-[11px]">
                        {signal.screen3.stop_price != null
                          ? `₹${signal.screen3.stop_price.toFixed(2)}`
                          : "—"}
                      </span>
                    </div>
                  </div>

                  <p className="text-[10px] text-muted leading-relaxed">
                    {signal.recommendation.reason}
                  </p>

                  {/* Validation */}
                  {signal.validation && (
                    <div className="flex items-center gap-1.5 text-[10px]">
                      {signal.validation.is_valid ? (
                        <span className="flex items-center gap-1 text-green">
                          <ShieldCheck className="w-3 h-3" /> Validated
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-red">
                          <ShieldAlert className="w-3 h-3" /> Blocked
                        </span>
                      )}
                    </div>
                  )}
                </div>
              )}
            </Section>
          </div>

          {/* System status — narrower */}
          <div className="lg:col-span-2">
            <Section title="System Status" delay={360}>
              <div className="p-3.5 space-y-3">
                {([
                  {
                    icon: Server,
                    label: "API Server",
                    ok: !!health,
                    text: health ? "Online" : "Offline",
                  },
                  {
                    icon: wsConnected ? Wifi : WifiOff,
                    label: "Market Feed",
                    ok: wsConnected,
                    text: wsConnected ? "Connected" : "Disconnected",
                  },
                ] as const).map(({ icon: Ic, label, ok, text }) => (
                  <div key={label} className="flex items-center justify-between text-[11px]">
                    <span className="flex items-center gap-2 text-muted">
                      <Ic className="w-3.5 h-3.5" />
                      {label}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className={cn("w-1.5 h-1.5 rounded-full", ok ? "bg-green" : "bg-red")} />
                      <span className={ok ? "text-green" : "text-red"}>{text}</span>
                    </span>
                  </div>
                ))}

                <div className="flex items-center justify-between text-[11px]">
                  <span className="flex items-center gap-2 text-muted">
                    <CircleDot className="w-3.5 h-3.5" />
                    Trading Mode
                  </span>
                  <span
                    className={cn(
                      "px-1.5 py-0.5 rounded text-[9px] font-bold",
                      mode === "PAPER" ? "bg-amber/10 text-amber" : "bg-green/10 text-green"
                    )}
                  >
                    {mode}
                  </span>
                </div>

                <div className="flex items-center justify-between text-[11px]">
                  <span className="flex items-center gap-2 text-muted">
                    {riskOk ? <ShieldCheck className="w-3.5 h-3.5" /> : <ShieldAlert className="w-3.5 h-3.5" />}
                    Circuit Breaker
                  </span>
                  <span className={cn("text-[10px] font-semibold", riskOk ? "text-green" : "text-red")}>
                    {risk?.six_percent_rule?.is_halted ? "HALTED" : riskOk ? "Active" : "Warning"}
                  </span>
                </div>

                {/* Risk details */}
                {risk && (
                  <div className="border-t border-border/50 pt-3 mt-1 space-y-2">
                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-muted">Per-trade risk limit</span>
                      <span className="font-mono text-foreground">{risk.two_percent_rule.max_risk_per_trade_pct}%</span>
                    </div>
                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-muted">Risk budget remaining</span>
                      <span className="font-mono text-foreground">₹{inr(risk.six_percent_rule.remaining_budget)}</span>
                    </div>
                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-muted">Min signal score</span>
                      <span className="font-mono text-foreground">{risk.min_signal_score}</span>
                    </div>
                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-muted">Open positions</span>
                      <span className="font-mono text-foreground">{risk.six_percent_rule.open_positions_count}</span>
                    </div>
                  </div>
                )}
              </div>
            </Section>
          </div>
        </div>
      </div>
    </div>
  );
}
