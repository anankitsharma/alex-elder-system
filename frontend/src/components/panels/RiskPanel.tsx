"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchRiskSummary,
  calculatePositionSize,
  type RiskSummary,
  type PositionSizeResult,
} from "@/lib/api";

export default function RiskPanel() {
  const [risk, setRisk] = useState<RiskSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<"overview" | "calculator">("overview");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchRiskSummary();
      setRisk(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="flex border-b border-border text-xs">
        <button
          className={`px-3 py-1.5 ${tab === "overview" ? "text-accent border-b border-accent" : "text-muted"}`}
          onClick={() => setTab("overview")}
        >
          Risk Overview
        </button>
        <button
          className={`px-3 py-1.5 ${tab === "calculator" ? "text-accent border-b border-accent" : "text-muted"}`}
          onClick={() => setTab("calculator")}
        >
          Position Sizer
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 text-xs">
        {tab === "overview" ? (
          <RiskOverview risk={risk} loading={loading} />
        ) : (
          <PositionCalculator />
        )}
      </div>
    </div>
  );
}

function RiskOverview({
  risk,
  loading,
}: {
  risk: RiskSummary | null;
  loading: boolean;
}) {
  if (loading && !risk) return <div className="text-muted p-2">Loading...</div>;
  if (!risk) return <div className="text-muted p-2">No data</div>;

  const cb = risk.six_percent_rule;
  const exposurePct = cb.exposure_pct || 0;
  const maxPct = cb.max_portfolio_risk_pct || 6;
  const barWidth = Math.min((exposurePct / maxPct) * 100, 100);
  const isWarning = exposurePct > maxPct * 0.7;
  const isDanger = cb.is_halted || exposurePct >= maxPct;

  return (
    <div className="space-y-3">
      {/* 2% Rule */}
      <div className="bg-surface-2 rounded p-2">
        <div className="text-muted mb-1">2% Rule (Per Trade)</div>
        <div className="text-lg font-mono text-accent">
          {risk.two_percent_rule.max_risk_per_trade_pct}%
        </div>
        <div className="text-muted mt-0.5">{risk.two_percent_rule.description}</div>
      </div>

      {/* 6% Rule */}
      <div className="bg-surface-2 rounded p-2">
        <div className="flex items-center justify-between mb-1">
          <span className="text-muted">6% Rule (Monthly)</span>
          {cb.is_halted && (
            <span className="text-[10px] bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded">
              HALTED
            </span>
          )}
        </div>

        {/* Progress bar */}
        <div className="h-2 bg-surface rounded-full overflow-hidden mb-1">
          <div
            className={`h-full rounded-full transition-all ${
              isDanger ? "bg-red-500" : isWarning ? "bg-amber-500" : "bg-green-500"
            }`}
            style={{ width: `${barWidth}%` }}
          />
        </div>

        <div className="flex justify-between text-muted">
          <span>{exposurePct.toFixed(2)}% used</span>
          <span>{maxPct}% limit</span>
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-2">
          <div>
            <span className="text-muted">Realized Losses</span>
            <div className="font-mono text-red-400">
              {cb.realized_losses?.toLocaleString("en-IN", { style: "currency", currency: "INR" }) || "₹0"}
            </div>
          </div>
          <div>
            <span className="text-muted">Open Risk</span>
            <div className="font-mono text-amber-400">
              {cb.open_risk?.toLocaleString("en-IN", { style: "currency", currency: "INR" }) || "₹0"}
            </div>
          </div>
          <div>
            <span className="text-muted">Remaining Budget</span>
            <div className="font-mono text-green-400">
              {cb.remaining_budget?.toLocaleString("en-IN", { style: "currency", currency: "INR" }) || "₹0"}
            </div>
          </div>
          <div>
            <span className="text-muted">Positions</span>
            <div className="font-mono">{cb.open_positions_count || 0}</div>
          </div>
        </div>
      </div>

      {/* Trading status */}
      <div className="bg-surface-2 rounded p-2">
        <div className="text-muted mb-1">Status</div>
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${cb.is_allowed ? "bg-green-500" : "bg-red-500"}`}
          />
          <span>{cb.is_allowed ? "Trading Active" : "Trading Halted"}</span>
          <span className="text-muted ml-auto">{risk.trading_mode}</span>
        </div>
        {cb.halt_reason && (
          <div className="text-red-400 mt-1">{cb.halt_reason}</div>
        )}
      </div>
    </div>
  );
}

function PositionCalculator() {
  const [entry, setEntry] = useState("");
  const [stop, setStop] = useState("");
  const [equity, setEquity] = useState("1000000");
  const [lotSize, setLotSize] = useState("1");
  const [result, setResult] = useState<PositionSizeResult | null>(null);
  const [error, setError] = useState("");

  const calculate = async () => {
    setError("");
    setResult(null);
    try {
      const data = await calculatePositionSize(
        parseFloat(entry),
        parseFloat(stop),
        parseFloat(equity),
        parseInt(lotSize)
      );
      setResult(data);
    } catch (e: any) {
      setError(e.message || "Calculation failed");
    }
  };

  return (
    <div className="space-y-2">
      <div className="text-muted mb-1">2% Rule Position Sizer</div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-muted block mb-0.5">Entry Price</label>
          <input
            type="number"
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
            className="w-full bg-surface border border-border rounded px-2 py-1 text-xs"
            placeholder="100.00"
          />
        </div>
        <div>
          <label className="text-muted block mb-0.5">Stop Price</label>
          <input
            type="number"
            value={stop}
            onChange={(e) => setStop(e.target.value)}
            className="w-full bg-surface border border-border rounded px-2 py-1 text-xs"
            placeholder="95.00"
          />
        </div>
        <div>
          <label className="text-muted block mb-0.5">Account Equity</label>
          <input
            type="number"
            value={equity}
            onChange={(e) => setEquity(e.target.value)}
            className="w-full bg-surface border border-border rounded px-2 py-1 text-xs"
          />
        </div>
        <div>
          <label className="text-muted block mb-0.5">Lot Size</label>
          <input
            type="number"
            value={lotSize}
            onChange={(e) => setLotSize(e.target.value)}
            className="w-full bg-surface border border-border rounded px-2 py-1 text-xs"
          />
        </div>
      </div>

      <button
        onClick={calculate}
        disabled={!entry || !stop || !equity}
        className="w-full bg-accent/20 text-accent rounded py-1.5 text-xs hover:bg-accent/30 disabled:opacity-50"
      >
        Calculate
      </button>

      {error && <div className="text-red-400 text-xs">{error}</div>}

      {result && (
        <div className="bg-surface-2 rounded p-2 space-y-1">
          {result.is_valid ? (
            <>
              <div className="flex justify-between">
                <span className="text-muted">Shares</span>
                <span className="font-mono text-green-400">{result.shares}</span>
              </div>
              {result.lots !== null && (
                <div className="flex justify-between">
                  <span className="text-muted">Lots</span>
                  <span className="font-mono">{result.lots}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-muted">Risk Amount</span>
                <span className="font-mono text-red-400">₹{result.risk_amount.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Risk %</span>
                <span className="font-mono">{result.actual_risk_pct}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Position Value</span>
                <span className="font-mono">₹{result.position_value.toLocaleString()}</span>
              </div>
            </>
          ) : (
            <div className="text-red-400">{result.reason}</div>
          )}
        </div>
      )}
    </div>
  );
}
