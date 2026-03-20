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
