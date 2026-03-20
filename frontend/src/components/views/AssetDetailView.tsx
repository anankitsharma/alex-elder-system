"use client";

import { useState, useEffect } from "react";
import { fetchAssetDetail, type AssetDetailResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ArrowLeft, BarChart3, ShoppingCart, Loader2 } from "lucide-react";

interface Props {
  symbol: string;
  exchange: string;
  onBack: () => void;
  onNavigate: (view: string) => void;
}

const TF_LABELS: Record<string, string> = {
  "1w": "Weekly", "1d": "Daily", "4h": "4H", "1h": "Hourly",
  "15m": "15min", "5m": "5min", "1m": "1min",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface overflow-hidden">
      <div className="px-4 py-2 border-b border-border">
        <span className="text-[11px] font-semibold text-foreground">{title}</span>
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

function ActiveTradesSection({ positions, orders, ltp, lotSize }: { positions: any[]; orders: any[]; ltp: number; lotSize: number }) {
  if (positions.length === 0) return null;

  return (
    <Section title={`Active Paper Trades (${positions.length})`}>
      <div className="space-y-3">
        {positions.map((pos: any, i: number) => {
          const isLong = pos.direction === "LONG";
          const entry = pos.entry_price ?? 0;
          const qty = pos.quantity ?? 0;
          const stop = pos.stop_price ?? 0;
          const pnlPerShare = isLong ? ltp - entry : entry - ltp;
          const totalPnl = pnlPerShare * qty;
          const pnlPct = entry > 0 ? (pnlPerShare / entry) * 100 : 0;
          const riskPerShare = Math.abs(entry - stop);
          const totalRisk = riskPerShare * qty;
          const lots = lotSize > 1 ? Math.round(qty / lotSize) : qty;
          const isProfit = pnlPerShare >= 0;

          // Find associated order
          const order = orders.find((o: any) =>
            o.direction === (isLong ? "BUY" : "SELL") && o.status === "COMPLETE" && Math.abs((o.filled_price ?? o.price ?? 0) - entry) < 1
          );

          return (
            <div key={pos.id || i} className={cn(
              "rounded-lg border p-4",
              isProfit ? "border-green-500/30 bg-green-500/5" : "border-red-500/30 bg-red-500/5"
            )}>
              {/* Header */}
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className={cn("text-[12px] font-bold", isLong ? "text-green-400" : "text-red-400")}>
                    {isLong ? "📈 LONG" : "📉 SHORT"}
                  </span>
                  <span className="text-[9px] text-muted px-1 py-0.5 rounded bg-surface-2">{pos.mode}</span>
                  <span className="text-[9px] text-muted">{pos.created_at?.slice(0, 16).replace("T", " ")}</span>
                </div>
                <div className={cn("text-[14px] font-bold font-mono", isProfit ? "text-green-400" : "text-red-400")}>
                  {isProfit ? "+" : ""}₹{totalPnl.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                  <span className="text-[10px] ml-1">({isProfit ? "+" : ""}{pnlPct.toFixed(2)}%)</span>
                </div>
              </div>

              {/* Details grid */}
              <div className="grid grid-cols-3 md:grid-cols-6 gap-3 text-[10px]">
                <div>
                  <div className="text-muted">Entry</div>
                  <div className="font-mono text-foreground">₹{entry.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</div>
                </div>
                <div>
                  <div className="text-muted">Current (LTP)</div>
                  <div className="font-mono text-foreground">₹{ltp.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</div>
                </div>
                <div>
                  <div className="text-muted">Stop Loss</div>
                  <div className="font-mono text-red-400">₹{stop.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</div>
                </div>
                <div>
                  <div className="text-muted">Quantity</div>
                  <div className="font-mono text-foreground">{qty}{lotSize > 1 ? ` (${lots} lot${lots !== 1 ? "s" : ""})` : ""}</div>
                </div>
                <div>
                  <div className="text-muted">P&L / Share</div>
                  <div className={cn("font-mono", isProfit ? "text-green-400" : "text-red-400")}>
                    {isProfit ? "+" : ""}₹{pnlPerShare.toFixed(2)}
                  </div>
                </div>
                <div>
                  <div className="text-muted">Risk (total)</div>
                  <div className="font-mono text-amber-400">₹{totalRisk.toLocaleString("en-IN", { maximumFractionDigits: 0 })}</div>
                </div>
              </div>

              {/* Risk:Reward bar */}
              {riskPerShare > 0 && (
                <div className="mt-3 pt-2 border-t border-border/30">
                  <div className="flex items-center justify-between text-[9px] text-muted mb-1">
                    <span>Stop</span>
                    <span>Entry</span>
                    <span>Current</span>
                  </div>
                  <div className="h-2 bg-surface-2 rounded-full overflow-hidden flex">
                    {/* Risk zone (entry to stop) */}
                    <div className="h-full bg-red-500/40" style={{ width: "33%" }} />
                    {/* Current position */}
                    <div className={cn("h-full", isProfit ? "bg-green-500/60" : "bg-red-500/60")}
                      style={{ width: `${Math.min(67, Math.abs(pnlPerShare / riskPerShare) * 33)}%` }} />
                  </div>
                  <div className="text-[9px] text-muted mt-1">
                    R:R achieved: {(Math.abs(pnlPerShare) / riskPerShare).toFixed(1)}x
                    {order?.order_id && <span className="ml-3">Order: {order.order_id}</span>}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Section>
  );
}

function TradingPlanSection({ plan, symbol }: { plan: any; symbol: string }) {
  if (!plan) return null;

  const dir = plan.direction;
  const dirColor = dir === "LONG" ? "text-green-400" : dir === "SHORT" ? "text-red-400" : "text-muted";
  const dirEmoji = dir === "LONG" ? "📈" : dir === "SHORT" ? "📉" : "⏸";

  const statusColors: Record<string, string> = {
    WATCHING: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    ENTRY_PENDING: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    IN_TRADE: "bg-green-500/10 text-green-400 border-green-500/20",
    COMPLETED: "bg-surface-2 text-muted border-border",
  };

  const entry = plan.entry_price || plan.projected_entry;
  const isProjected = !plan.has_signal && plan.projected_entry;
  const kl = plan.key_levels || {};

  return (
    <Section title={`Trading Plan — ${symbol}`}>
      {/* Status + Direction */}
      <div className="flex items-center gap-3 mb-4">
        <span className={cn("px-2 py-1 rounded text-[10px] font-bold border", statusColors[plan.status] ?? "text-muted")}>
          {plan.status}
        </span>
        <span className={cn("text-[13px] font-bold", dirColor)}>
          {dirEmoji} {dir ?? "NO DIRECTION"}
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Left: Entry + Stops + Targets */}
        <div className="space-y-3">
          {/* Entry */}
          <div className={cn("rounded-lg border p-3", isProjected ? "border-amber-500/30 bg-amber-500/5" : plan.has_signal ? "border-green-500/30 bg-green-500/5" : "border-border")}>
            <div className="text-[10px] text-muted mb-1">
              {isProjected ? "Projected Entry (next trigger)" : plan.has_signal ? "Signal Entry" : "Entry"}
            </div>
            <div className="flex items-center justify-between">
              <div>
                <span className="text-[16px] font-bold font-mono text-foreground">
                  {entry ? `₹${entry.toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "—"}
                </span>
                {plan.projected_entry_type && (
                  <span className="ml-2 text-[9px] text-muted px-1 py-0.5 rounded bg-surface-2">
                    {plan.projected_entry_type}
                  </span>
                )}
              </div>
              {isProjected && (
                <span className="text-[9px] text-amber-400">
                  Will trigger when Screen 3 confirms
                </span>
              )}
            </div>
          </div>

          {/* Stops */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-3">
              <div className="text-[10px] text-muted mb-1">Initial Stop Loss</div>
              <div className="text-[14px] font-bold font-mono text-red-400">
                {plan.initial_stop ? `₹${plan.initial_stop.toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "—"}
              </div>
              <div className="text-[9px] text-muted mt-1">SafeZone calculated</div>
            </div>
            <div className="rounded-lg border border-orange-500/20 bg-orange-500/5 p-3">
              <div className="text-[10px] text-muted mb-1">Trailing Stop (current)</div>
              <div className="text-[14px] font-bold font-mono text-orange-400">
                {plan.trailing_stop ? `₹${plan.trailing_stop.toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : plan.initial_stop ? `₹${plan.initial_stop.toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "—"}
              </div>
              <div className="text-[9px] text-muted mt-1">Updates with SafeZone each bar</div>
            </div>
          </div>

          {/* P&L */}
          {plan.unrealized_pnl_per_share != null && entry && (
            <div className={cn("rounded-lg border p-3", plan.unrealized_pnl_per_share >= 0 ? "border-green-500/20 bg-green-500/5" : "border-red-500/20 bg-red-500/5")}>
              <div className="text-[10px] text-muted mb-1">Unrealized P&L (per share)</div>
              <div className={cn("text-[16px] font-bold font-mono", plan.unrealized_pnl_per_share >= 0 ? "text-green-400" : "text-red-400")}>
                {plan.unrealized_pnl_per_share >= 0 ? "+" : ""}₹{plan.unrealized_pnl_per_share.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </div>
              <div className="text-[9px] text-muted mt-1">
                LTP: ₹{kl.ltp?.toLocaleString("en-IN", { minimumFractionDigits: 2 })} vs Entry: ₹{entry?.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </div>
            </div>
          )}
        </div>

        {/* Right: Targets + Key Levels */}
        <div className="space-y-3">
          {/* Targets */}
          {plan.targets && plan.targets.length > 0 && (
            <div className="rounded-lg border border-border p-3">
              <div className="text-[10px] text-muted mb-2">Targets (Risk:Reward)</div>
              <div className="space-y-2">
                {plan.targets.map((t: any) => (
                  <div key={t.ratio} className="flex items-center justify-between">
                    <span className="text-[10px] text-muted">{t.ratio}</span>
                    <div className="flex-1 mx-2 h-1 bg-surface-2 rounded-full overflow-hidden">
                      <div className="h-full bg-green-500/60 rounded-full" style={{ width: `${Math.min(100, parseInt(t.ratio.split(":")[1]) * 33)}%` }} />
                    </div>
                    <span className="font-mono text-[11px] text-green-400">₹{t.price.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                    <span className="text-[9px] text-muted ml-2">+₹{t.reward.toFixed(0)}</span>
                  </div>
                ))}
              </div>
              {plan.risk_reward && (
                <div className="mt-2 pt-2 border-t border-border/50 text-[10px] text-muted">{plan.risk_reward}</div>
              )}
            </div>
          )}

          {/* Key Levels */}
          <div className="rounded-lg border border-border p-3">
            <div className="text-[10px] text-muted mb-2">Key Levels</div>
            <div className="space-y-1.5 text-[11px]">
              {kl.ltp && (
                <div className="flex justify-between">
                  <span className="text-muted">LTP</span>
                  <span className="font-mono text-foreground">₹{kl.ltp.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                </div>
              )}
              {kl.prev_high && (
                <div className="flex justify-between">
                  <span className="text-muted">Prev High</span>
                  <span className="font-mono text-green-400/70">₹{kl.prev_high.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                </div>
              )}
              {kl.prev_low && (
                <div className="flex justify-between">
                  <span className="text-muted">Prev Low</span>
                  <span className="font-mono text-red-400/70">₹{kl.prev_low.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                </div>
              )}
              {kl.safezone_long && (
                <div className="flex justify-between">
                  <span className="text-muted">SafeZone Long</span>
                  <span className="font-mono text-green-400/50">₹{kl.safezone_long.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                </div>
              )}
              {kl.safezone_short && (
                <div className="flex justify-between">
                  <span className="text-muted">SafeZone Short</span>
                  <span className="font-mono text-red-400/50">₹{kl.safezone_short.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </Section>
  );
}

export default function AssetDetailView({ symbol, exchange, onBack, onNavigate }: Props) {
  const [data, setData] = useState<AssetDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchAssetDetail(symbol, exchange)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [symbol, exchange]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 text-muted animate-spin" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3">
        <span className="text-muted">Failed to load asset detail</span>
        <button onClick={onBack} className="text-accent text-sm hover:underline">Back to Dashboard</button>
      </div>
    );
  }

  const s = data.sizing;
  const al = data.alignment;
  const summary = data.summary;
  const ltp = summary?.ltp;
  const changePct = summary?.change_pct;
  const isUp = (changePct ?? 0) >= 0;
  const tfs = summary?.screen_timeframes || {};

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-6 h-14 border-b border-border shrink-0">
        <div className="flex items-center gap-4">
          <button onClick={onBack} className="p-1.5 rounded hover:bg-surface-2 text-muted hover:text-foreground">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="flex items-center gap-3">
            <span className="text-lg font-bold text-foreground">{symbol}</span>
            <span className="text-[10px] text-muted px-1.5 py-0.5 rounded bg-surface-2">{exchange}</span>
            {summary?.grade && (
              <span className={cn(
                "text-[10px] px-1.5 py-0.5 rounded font-bold",
                summary.grade === "A" || summary.grade === "B" ? "bg-green-500/15 text-green-400" :
                summary.grade === "C" ? "bg-amber-500/15 text-amber-400" : "bg-red-500/15 text-red-400"
              )}>Grade {summary.grade}</span>
            )}
          </div>
          {ltp && (
            <div className="flex items-center gap-2">
              <span className="font-mono text-foreground text-lg">
                ₹{ltp.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </span>
              {changePct != null && (
                <span className={cn("text-sm font-mono", isUp ? "text-green-400" : "text-red-400")}>
                  {isUp ? "+" : ""}{changePct.toFixed(2)}%
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted">Lot: <b className="text-foreground">{data.lot_size}</b></span>
          {data.lot_value && (
            <span className="text-[10px] text-muted">1 Lot: <b className="text-foreground">₹{data.lot_value.toLocaleString("en-IN")}</b></span>
          )}
          <button onClick={() => onNavigate("charts")} className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-accent/10 text-accent hover:bg-accent/20">
            <BarChart3 className="w-3 h-3" /> Charts
          </button>
          <button onClick={() => onNavigate("trades")} className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-green-500/10 text-green-400 hover:bg-green-500/20">
            <ShoppingCart className="w-3 h-3" /> Trade
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-5 space-y-4 max-w-[1400px] mx-auto w-full">

        {/* ── Trading Plan ── */}
        {data.trading_plan && <TradingPlanSection plan={data.trading_plan} symbol={symbol} />}

        {/* ── Position Sizing Calculator ── */}
        <Section title="Position Sizing — Elder's 2% Rule">
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 text-[11px]">
            <div>
              <div className="text-muted mb-1">Account Equity</div>
              <div className="font-mono text-foreground text-[13px]">₹{s.equity.toLocaleString("en-IN")}</div>
            </div>
            <div>
              <div className="text-muted mb-1">Risk (2%)</div>
              <div className="font-mono text-foreground text-[13px]">₹{s.max_risk_amount.toLocaleString("en-IN")}</div>
            </div>
            <div>
              <div className="text-muted mb-1">Entry Price</div>
              <div className="font-mono text-foreground text-[13px]">{s.entry_price ? `₹${s.entry_price.toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "—"}</div>
            </div>
            <div>
              <div className="text-muted mb-1">Stop Loss</div>
              <div className="font-mono text-red-400 text-[13px]">{s.stop_price ? `₹${s.stop_price.toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "—"}</div>
            </div>
            <div>
              <div className="text-muted mb-1">Risk/Share</div>
              <div className="font-mono text-foreground text-[13px]">{s.risk_per_share ? `₹${s.risk_per_share.toFixed(2)}` : "—"}</div>
            </div>
            <div>
              <div className="text-muted mb-1">Lot Size</div>
              <div className="font-mono text-foreground text-[13px]">{data.lot_size}</div>
            </div>
          </div>
          {s.entry_price && s.stop_price && (
            <div className="mt-4 pt-4 border-t border-border grid grid-cols-2 md:grid-cols-4 gap-4 text-[11px]">
              <div>
                <div className="text-muted mb-1">Raw Shares</div>
                <div className="font-mono text-foreground text-[15px] font-bold">{s.raw_shares}</div>
              </div>
              <div>
                <div className="text-muted mb-1">Lots (adjusted)</div>
                <div className="font-mono text-green-400 text-[15px] font-bold">
                  {s.lots} lot{s.lots !== 1 ? "s" : ""} = {s.adjusted_shares} shares
                </div>
              </div>
              <div>
                <div className="text-muted mb-1">Position Value</div>
                <div className="font-mono text-foreground text-[15px]">{s.position_value ? `₹${s.position_value.toLocaleString("en-IN")}` : "—"}</div>
              </div>
              <div>
                <div className="text-muted mb-1">Total Risk</div>
                <div className="font-mono text-amber-400 text-[15px]">
                  ₹{(s.adjusted_shares * (s.risk_per_share ?? 0)).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                </div>
              </div>
            </div>
          )}
        </Section>

        {/* ── Screen Alignment ── */}
        <Section title="Triple Screen Alignment">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[
              { num: "1", label: "Tide (Trend)", tf: tfs["1"], aligned: al?.screen1, value: summary?.tide, color: summary?.tide === "BULLISH" ? "text-green-400" : summary?.tide === "BEARISH" ? "text-red-400" : "text-muted" },
              { num: "2", label: "Wave (Oscillator)", tf: tfs["2"], aligned: al?.screen2, value: summary?.wave_signal, color: summary?.wave_signal === "BUY" ? "text-green-400" : summary?.wave_signal === "SELL" ? "text-red-400" : "text-muted" },
              { num: "3", label: "Entry (Precision)", tf: tfs["3"], aligned: al?.screen3, value: summary?.action, color: summary?.action === "BUY" ? "text-green-400" : summary?.action === "SELL" ? "text-red-400" : "text-muted" },
            ].map((screen) => (
              <div key={screen.num} className={cn(
                "rounded-lg border p-3",
                screen.aligned ? "border-green-500/40 bg-green-500/5" : "border-border",
              )}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className={cn("w-2 h-2 rounded-full", screen.aligned ? "bg-green-500" : "bg-red-500/40")} />
                    <span className="text-[11px] font-semibold text-foreground">Screen {screen.num} — {screen.label}</span>
                  </div>
                  <span className="text-[9px] text-muted">{TF_LABELS[screen.tf ?? ""] ?? screen.tf ?? "—"}</span>
                </div>
                <div className={cn("text-lg font-bold", screen.color)}>
                  {screen.value ?? "—"}
                </div>
              </div>
            ))}
          </div>
          {al?.description && (
            <div className={cn(
              "mt-3 text-center text-[12px] font-semibold py-2 rounded",
              al.level === 3 ? "bg-green-500/10 text-green-400" :
              al.level === 2 ? "bg-orange-500/10 text-orange-400" :
              al.level === 1 ? "bg-amber-500/10 text-amber-400" : "text-muted",
            )}>
              {al.description}
            </div>
          )}
        </Section>

        {/* ── Active Paper Trades ── */}
        <ActiveTradesSection
          positions={data.positions.filter((p: any) => p.status === "OPEN")}
          orders={data.orders}
          ltp={ltp ?? 0}
          lotSize={data.lot_size}
        />

        {/* ── Signal History ── */}
        <Section title={`Signal History (${data.signals.length})`}>
          {data.signals.length === 0 ? (
            <div className="text-center text-muted text-[11px] py-4">No signals recorded</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="border-b border-border text-muted">
                    <th className="text-left py-1 px-2">Time</th>
                    <th className="text-center py-1 px-2">Direction</th>
                    <th className="text-right py-1 px-2">Score</th>
                    <th className="text-right py-1 px-2">Entry</th>
                    <th className="text-right py-1 px-2">Stop</th>
                    <th className="text-center py-1 px-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.signals.map((sig: any, i: number) => (
                    <tr key={sig.id || i} className="border-b border-border/30">
                      <td className="py-1.5 px-2 text-muted">{sig.created_at?.slice(0, 16).replace("T", " ") ?? "—"}</td>
                      <td className={cn("text-center py-1.5 px-2 font-semibold", sig.direction === "LONG" ? "text-green-400" : "text-red-400")}>{sig.direction}</td>
                      <td className="text-right py-1.5 px-2">{sig.score}%</td>
                      <td className="text-right py-1.5 px-2 font-mono">{sig.entry_price?.toFixed(2) ?? "—"}</td>
                      <td className="text-right py-1.5 px-2 font-mono text-red-400/60">{sig.stop_price?.toFixed(2) ?? "—"}</td>
                      <td className="text-center py-1.5 px-2">
                        <span className={cn("text-[9px] px-1 py-0.5 rounded", sig.status === "ACTIVE" ? "bg-green-500/15 text-green-400" : "bg-surface-2 text-muted")}>{sig.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>

        {/* ── Order + Position History ── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Section title={`Orders (${data.orders.length})`}>
            {data.orders.length === 0 ? (
              <div className="text-center text-muted text-[11px] py-4">No orders</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[10px]">
                  <thead>
                    <tr className="border-b border-border text-muted">
                      <th className="text-left py-1 px-2">Time</th>
                      <th className="text-center py-1 px-2">Dir</th>
                      <th className="text-right py-1 px-2">Qty</th>
                      <th className="text-right py-1 px-2">Price</th>
                      <th className="text-center py-1 px-2">Mode</th>
                      <th className="text-center py-1 px-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.orders.map((o: any, i: number) => (
                      <tr key={o.id || i} className="border-b border-border/30">
                        <td className="py-1.5 px-2 text-muted">{o.created_at?.slice(0, 16).replace("T", " ") ?? "—"}</td>
                        <td className={cn("text-center py-1.5 px-2 font-semibold", o.direction === "BUY" ? "text-green-400" : "text-red-400")}>{o.direction}</td>
                        <td className="text-right py-1.5 px-2">{o.quantity}</td>
                        <td className="text-right py-1.5 px-2 font-mono">{o.filled_price?.toFixed(2) ?? o.price?.toFixed(2) ?? "—"}</td>
                        <td className="text-center py-1.5 px-2"><span className="text-[9px] px-1 py-0.5 rounded bg-surface-2">{o.mode}</span></td>
                        <td className="text-center py-1.5 px-2"><span className={cn("text-[9px] px-1 py-0.5 rounded", o.status === "COMPLETE" ? "bg-green-500/15 text-green-400" : "bg-surface-2 text-muted")}>{o.status}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          <Section title={`Positions (${data.positions.length})`}>
            {data.positions.length === 0 ? (
              <div className="text-center text-muted text-[11px] py-4">No positions</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[10px]">
                  <thead>
                    <tr className="border-b border-border text-muted">
                      <th className="text-left py-1 px-2">Time</th>
                      <th className="text-center py-1 px-2">Dir</th>
                      <th className="text-right py-1 px-2">Qty</th>
                      <th className="text-right py-1 px-2">Entry</th>
                      <th className="text-right py-1 px-2">Stop</th>
                      <th className="text-center py-1 px-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.positions.map((p: any, i: number) => (
                      <tr key={p.id || i} className="border-b border-border/30">
                        <td className="py-1.5 px-2 text-muted">{p.created_at?.slice(0, 16).replace("T", " ") ?? "—"}</td>
                        <td className={cn("text-center py-1.5 px-2 font-semibold", p.direction === "LONG" ? "text-green-400" : "text-red-400")}>{p.direction}</td>
                        <td className="text-right py-1.5 px-2">{p.quantity}</td>
                        <td className="text-right py-1.5 px-2 font-mono">{p.entry_price?.toFixed(2)}</td>
                        <td className="text-right py-1.5 px-2 font-mono text-red-400/60">{p.stop_price?.toFixed(2) ?? "—"}</td>
                        <td className="text-center py-1.5 px-2"><span className={cn("text-[9px] px-1 py-0.5 rounded", p.status === "OPEN" ? "bg-green-500/15 text-green-400" : "bg-surface-2 text-muted")}>{p.status}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}
