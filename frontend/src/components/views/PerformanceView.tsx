"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Loader2, TrendingUp, TrendingDown, Target, Shield, BarChart3, Award } from "lucide-react";

interface PerformanceData {
  starting_equity: number;
  current_equity: number;
  total_pnl: number;
  unrealized_pnl: number;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number | string;
  expectancy: number;
  max_drawdown_pct: number;
  r_multiples: number[];
  equity_curve: { date: string; equity: number }[];
  open_positions: number;
  recent_trades: any[];
}

function StatCard({ label, value, sub, icon: Icon, color }: {
  label: string; value: React.ReactNode; sub?: string;
  icon: typeof TrendingUp; color: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <div className="flex items-center gap-2 mb-1">
        <Icon className="w-3.5 h-3.5" style={{ color }} />
        <span className="text-[10px] text-muted">{label}</span>
      </div>
      <div className="text-[16px] font-bold font-mono text-foreground">{value}</div>
      {sub && <div className="text-[9px] text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

function EquityCurve({ data }: { data: { date: string; equity: number }[] }) {
  if (data.length < 2) return <div className="text-center text-muted text-[11px] py-8">No trades yet</div>;

  const min = Math.min(...data.map(d => d.equity));
  const max = Math.max(...data.map(d => d.equity));
  const range = max - min || 1;
  const w = 100;
  const h = 40;

  const points = data.map((d, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((d.equity - min) / range) * h;
    return `${x},${y}`;
  }).join(" ");

  const isUp = data[data.length - 1].equity >= data[0].equity;

  return (
    <div className="py-2">
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-24" preserveAspectRatio="none">
        <polyline
          points={points}
          fill="none"
          stroke={isUp ? "#22c55e" : "#ef4444"}
          strokeWidth="0.5"
        />
        <polyline
          points={`0,${h} ${points} ${w},${h}`}
          fill={isUp ? "rgba(34,197,94,0.1)" : "rgba(239,68,68,0.1)"}
          stroke="none"
        />
      </svg>
      <div className="flex justify-between text-[9px] text-muted mt-1">
        <span>₹{data[0].equity.toLocaleString("en-IN")}</span>
        <span>₹{data[data.length - 1].equity.toLocaleString("en-IN")}</span>
      </div>
    </div>
  );
}

function RMultipleChart({ data }: { data: number[] }) {
  if (data.length === 0) return <div className="text-center text-muted text-[11px] py-4">No R-multiples</div>;

  const maxAbs = Math.max(...data.map(Math.abs), 1);

  return (
    <div className="flex items-end gap-0.5 h-16">
      {data.slice(-30).map((r, i) => (
        <div key={i} className="flex-1 flex flex-col justify-end">
          <div
            className={cn("rounded-sm min-h-[2px]", r >= 0 ? "bg-green-500" : "bg-red-500")}
            style={{ height: `${Math.abs(r) / maxAbs * 100}%` }}
            title={`${r}R`}
          />
        </div>
      ))}
    </div>
  );
}

export default function PerformanceView() {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("http://localhost:8000/api/strategy/pipeline/performance")
      .then(r => r.json())
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex items-center justify-center h-full"><Loader2 className="w-6 h-6 animate-spin text-muted" /></div>;
  if (!data) return <div className="flex items-center justify-center h-full text-muted">Failed to load performance data</div>;

  const pnlColor = data.total_pnl >= 0 ? "text-green-400" : "text-red-400";
  const isProfit = data.total_pnl >= 0;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex items-center px-6 h-11 border-b border-border shrink-0">
        <h1 className="text-[13px] font-semibold text-foreground">Performance Analytics</h1>
      </div>

      <div className="flex-1 overflow-auto p-5 space-y-4 max-w-[1400px] mx-auto w-full">
        {/* Key metrics */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <StatCard
            label="Total P&L" icon={isProfit ? TrendingUp : TrendingDown}
            color={isProfit ? "#22c55e" : "#ef4444"}
            value={<span className={pnlColor}>{isProfit ? "+" : ""}₹{data.total_pnl.toLocaleString("en-IN")}</span>}
            sub={`Unrealized: ₹${data.unrealized_pnl.toLocaleString("en-IN")}`}
          />
          <StatCard
            label="Win Rate" icon={Target} color="#f59e0b"
            value={`${data.win_rate}%`}
            sub={`${data.wins}W / ${data.losses}L of ${data.total_trades}`}
          />
          <StatCard
            label="Profit Factor" icon={BarChart3} color="#3b82f6"
            value={String(data.profit_factor)}
            sub={`Avg Win: ₹${data.avg_win.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`}
          />
          <StatCard
            label="Expectancy" icon={Award} color="#8b5cf6"
            value={`₹${data.expectancy.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`}
            sub="Per trade expected value"
          />
          <StatCard
            label="Max Drawdown" icon={Shield} color="#ef4444"
            value={`${data.max_drawdown_pct}%`}
            sub={`Equity: ₹${data.current_equity.toLocaleString("en-IN")}`}
          />
          <StatCard
            label="Open Positions" icon={BarChart3} color="#22c55e"
            value={String(data.open_positions)}
            sub={`Starting: ₹${data.starting_equity.toLocaleString("en-IN")}`}
          />
        </div>

        {/* Equity curve + R-multiples */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-lg border border-border bg-surface p-4">
            <div className="text-[11px] font-semibold text-foreground mb-2">Equity Curve</div>
            <EquityCurve data={data.equity_curve} />
          </div>
          <div className="rounded-lg border border-border bg-surface p-4">
            <div className="text-[11px] font-semibold text-foreground mb-2">R-Multiple Distribution (last 30)</div>
            <RMultipleChart data={data.r_multiples} />
            <div className="flex justify-between text-[9px] text-muted mt-1">
              <span>Avg R: {data.r_multiples.length > 0 ? (data.r_multiples.reduce((a, b) => a + b, 0) / data.r_multiples.length).toFixed(2) : "—"}R</span>
              <span>Best: {data.r_multiples.length > 0 ? Math.max(...data.r_multiples).toFixed(1) : "—"}R</span>
              <span>Worst: {data.r_multiples.length > 0 ? Math.min(...data.r_multiples).toFixed(1) : "—"}R</span>
            </div>
          </div>
        </div>

        {/* Recent trades table */}
        <div className="rounded-lg border border-border bg-surface overflow-hidden">
          <div className="px-4 py-2 border-b border-border">
            <span className="text-[11px] font-semibold text-foreground">Recent Trades ({data.recent_trades.length})</span>
          </div>
          {data.recent_trades.length === 0 ? (
            <div className="text-center text-muted text-[11px] py-8">No closed trades yet</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="border-b border-border text-muted">
                    <th className="text-left py-1.5 px-3">Date</th>
                    <th className="text-left py-1.5 px-3">Symbol</th>
                    <th className="text-center py-1.5 px-3">Dir</th>
                    <th className="text-right py-1.5 px-3">Entry</th>
                    <th className="text-right py-1.5 px-3">Exit</th>
                    <th className="text-right py-1.5 px-3">Qty</th>
                    <th className="text-right py-1.5 px-3">P&L</th>
                    <th className="text-right py-1.5 px-3">R-Mult</th>
                    <th className="text-center py-1.5 px-3">Mode</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_trades.map((t: any, i: number) => (
                    <tr key={i} className="border-b border-border/30 hover:bg-surface-2">
                      <td className="py-1.5 px-3 text-muted">{t.date}</td>
                      <td className="py-1.5 px-3 font-semibold text-foreground">{t.symbol}</td>
                      <td className={cn("text-center py-1.5 px-3 font-semibold", t.direction === "LONG" ? "text-green-400" : "text-red-400")}>{t.direction}</td>
                      <td className="text-right py-1.5 px-3 font-mono">{t.entry?.toFixed(2)}</td>
                      <td className="text-right py-1.5 px-3 font-mono">{t.exit?.toFixed(2)}</td>
                      <td className="text-right py-1.5 px-3">{t.qty}</td>
                      <td className={cn("text-right py-1.5 px-3 font-mono font-bold", t.pnl >= 0 ? "text-green-400" : "text-red-400")}>
                        {t.pnl >= 0 ? "+" : ""}₹{t.pnl?.toLocaleString("en-IN")}
                      </td>
                      <td className={cn("text-right py-1.5 px-3 font-mono", t.r_multiple >= 0 ? "text-green-400" : "text-red-400")}>
                        {t.r_multiple >= 0 ? "+" : ""}{t.r_multiple}R
                      </td>
                      <td className="text-center py-1.5 px-3">
                        <span className="text-[9px] px-1 py-0.5 rounded bg-surface-2">{t.mode}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
