"use client";

import { useState, useEffect, useCallback } from "react";
import { Sidebar, type ViewId } from "@/components/layout/Sidebar";
import { SymbolBar } from "@/components/layout/SymbolBar";
import { ThreeScreenView } from "@/components/chart/ThreeScreenView";
import TradingViewChart from "@/components/chart/TradingViewChart";
import { PositionsPanel } from "@/components/panels/PositionsPanel";
import { OrdersPanel } from "@/components/panels/OrdersPanel";
import { TradePanel } from "@/components/panels/TradePanel";
import { WatchlistPanel } from "@/components/panels/WatchlistPanel";
import { FundsPanel } from "@/components/panels/FundsPanel";
import RiskPanel from "@/components/panels/RiskPanel";
import SignalPanel from "@/components/panels/SignalPanel";
import DashboardView from "@/components/views/DashboardView";
import SettingsView from "@/components/views/SettingsView";
import AssetDetailView from "@/components/views/AssetDetailView";
import PerformanceView from "@/components/views/PerformanceView";
import AssetsView from "@/components/views/AssetsView";
import SymbolSearch from "@/components/ui/SymbolSearch";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { PipelineStatusBar } from "@/components/layout/PipelineStatusBar";
import { ToastContainer } from "@/components/ui/ToastContainer";
import { useTradingStore } from "@/store/useTradingStore";
import { useAuthStore } from "@/store/useAuthStore";
import { usePipelineInit } from "@/hooks/usePipelineInit";
// useWebSocket removed — caused 10/sec re-renders killing all charts
// Pipeline WebSocket (usePipelineInit) handles live data now
import { cn } from "@/lib/utils";
import { BarChart3, LayoutGrid, Loader2 } from "lucide-react";

type ChartMode = "single" | "three-screen";

// ── Login Form (inline) ──────────────────────────────────
function LoginForm() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const login = useAuthStore((s) => s.login);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    const ok = await login(username, password);
    setSubmitting(false);
    if (!ok) setError("Invalid username or password");
  };

  return (
    <div className="flex items-center justify-center h-screen bg-background">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm p-8 rounded-xl bg-surface border border-border space-y-5"
      >
        {/* Brand */}
        <div className="flex flex-col items-center gap-2 mb-2">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-accent/25 to-accent/5 border border-accent/15 flex items-center justify-center">
            <span className="text-accent font-bold text-[16px] font-mono leading-none">E</span>
          </div>
          <h1 className="text-[15px] font-semibold text-foreground tracking-tight">Elder Trading System</h1>
          <p className="text-[11px] text-muted">Sign in to continue</p>
        </div>

        {error && (
          <div className="px-3 py-2 rounded-md bg-red-500/10 border border-red-500/20 text-[12px] text-red-400">
            {error}
          </div>
        )}

        <div className="space-y-1.5">
          <label className="text-[11px] font-medium text-muted">Username</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full px-3 py-2 rounded-md bg-background border border-border text-[13px] text-foreground placeholder:text-muted/50 focus:outline-none focus:ring-1 focus:ring-accent/40"
            placeholder="Enter username"
            autoFocus
            required
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-[11px] font-medium text-muted">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full px-3 py-2 rounded-md bg-background border border-border text-[13px] text-foreground placeholder:text-muted/50 focus:outline-none focus:ring-1 focus:ring-accent/40"
            placeholder="Enter password"
            required
          />
        </div>

        <button
          type="submit"
          disabled={submitting || !username || !password}
          className="w-full py-2 rounded-md bg-accent text-white text-[13px] font-medium hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {submitting ? "Signing in..." : "Sign In"}
        </button>
      </form>
    </div>
  );
}

// Auth wrapper — renders LoginForm or Dashboard based on auth state
export default function AuthGate() {
  const authLoading = useAuthStore((s) => s.loading);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const checkAuth = useAuthStore((s) => s.checkAuth);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  if (authLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <Loader2 className="w-6 h-6 text-muted animate-spin" />
      </div>
    );
  }
  if (!isAuthenticated) {
    return <LoginForm />;
  }

  return <Dashboard />;
}

// Main dashboard — only mounted when authenticated (avoids hook ordering issues)
function Dashboard() {
  const [view, setView] = useState<ViewId>("dashboard");
  const [searchOpen, setSearchOpen] = useState(false);
  const [chartMode, setChartMode] = useState<ChartMode>("single");

  // Zustand store — asset, data, pipeline state
  const symbol = useTradingStore((s) => s.symbol);
  const exchange = useTradingStore((s) => s.exchange);
  const interval = useTradingStore((s) => s.interval);
  const candles = useTradingStore((s) => s.candles);
  const indicators = useTradingStore((s) => s.indicators);
  const source = useTradingStore((s) => s.source);
  const loading = useTradingStore((s) => s.loading);
  const setAsset = useTradingStore((s) => s.setAsset);
  const setIntervalStore = useTradingStore((s) => s.setInterval);

  // Initialize pipeline (WebSocket, initial data, health polling)
  const { ready, wsManager } = usePipelineInit();

  // Pipeline WebSocket connection status from store
  const wsConnected = useTradingStore((s) => s.pipelineWsConnected);

  const handleSymbolChange = (sym: string, exch: string) => {
    setAsset(sym, exch);
    if (wsManager) {
      wsManager.trackSymbol(sym, exch);
    }
  };

  const handleAssetSelect = (sym: string, exch: string) => {
    handleSymbolChange(sym, exch);
    setView("asset-detail");
  };

  // Keyboard shortcuts
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      // Cmd+K / Ctrl+K = Symbol search
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
        return;
      }

      // Don't trigger if typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      switch (e.key) {
        case "1": setView("dashboard"); break;
        case "2": setView("charts"); break;
        case "3": setView("trades"); break;
        case "4": setView("signals"); break;
        case "5": setView("risk"); break;
        case "6": setView("performance"); break;
        case "7": setView("assets"); break;
        case "8": setView("portfolio"); break;
        case "Escape":
          if (view === "asset-detail") setView("dashboard");
          break;
      }

      // Timeframe shortcuts (only on charts view)
      if (view === "charts") {
        const tfMap: Record<string, string> = { "F1": "1m", "F2": "5m", "F3": "15m", "F4": "1h", "F5": "1d", "F6": "1w" };
        if (tfMap[e.key]) {
          e.preventDefault();
          setIntervalStore(tfMap[e.key]);
        }
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [view, setIntervalStore]);

  const handleSearchSelect = (sym: string, exch: string) => {
    handleSymbolChange(sym, exch);
    setView("asset-detail");
  };

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <SymbolSearch open={searchOpen} onClose={() => setSearchOpen(false)} onSelect={handleSearchSelect} />
      <Sidebar active={view} onChange={setView} />

      <div className="flex-1 flex flex-col min-w-0">
        {/* Pipeline status bar */}
        <PipelineStatusBar />

        {/* Signal toasts */}
        <ToastContainer />

        {/* ═══════ Dashboard ═══════════════════════════════════ */}
        {view === "dashboard" && (
          <ErrorBoundary label="Dashboard">
            <DashboardView
              symbol={symbol}
              exchange={exchange}
              wsConnected={wsConnected}
              candles={candles}
              indicators={indicators}
              onNavigate={(v) => setView(v as ViewId)}
              onAssetSelect={handleAssetSelect}
            />
          </ErrorBoundary>
        )}

        {/* ═══════ Charts ══════════════════════════════════════ */}
        {view === "charts" && (
          <div className="flex flex-col flex-1 min-h-0">
            <ErrorBoundary label="Symbol Bar">
              <SymbolBar
                symbol={symbol}
                exchange={exchange}
                interval={interval}
                onSymbolChange={handleSymbolChange}
                onIntervalChange={setIntervalStore}
              />
            </ErrorBoundary>

            {/* View mode toggle */}
            <div className="flex items-center gap-1 px-3 py-1 border-b border-border">
              <button
                className={cn(
                  "flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium transition-colors",
                  chartMode === "single"
                    ? "bg-accent/15 text-accent"
                    : "text-muted hover:text-foreground hover:bg-surface-2"
                )}
                onClick={() => setChartMode("single")}
              >
                <BarChart3 className="w-3 h-3" /> Single
              </button>
              <button
                className={cn(
                  "flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium transition-colors",
                  chartMode === "three-screen"
                    ? "bg-accent/15 text-accent"
                    : "text-muted hover:text-foreground hover:bg-surface-2"
                )}
                onClick={() => setChartMode("three-screen")}
              >
                <LayoutGrid className="w-3 h-3" /> Three Screen
              </button>
            </div>

            {/* Chart */}
            <div className="flex-1 min-h-0 relative overflow-hidden">
              {source === "demo" && !loading && candles.length > 0 && chartMode === "single" && (
                <div className="absolute top-2 right-4 z-20 px-2 py-0.5 rounded text-[10px] font-medium bg-amber/10 text-amber border border-amber/15">
                  DEMO DATA
                </div>
              )}
              <ErrorBoundary label="Chart">
                {chartMode === "single" ? (
                  loading ? (
                    <div className="flex items-center justify-center h-full">
                      <Loader2 className="w-5 h-5 text-muted animate-spin" />
                    </div>
                  ) : candles.length === 0 ? (
                    <div className="flex items-center justify-center h-full text-sm text-muted">
                      No data for {symbol}
                    </div>
                  ) : (
                    <TradingViewChart candles={candles} indicators={indicators} />
                  )
                ) : (
                  <ThreeScreenView symbol={symbol} exchange={exchange} />
                )}
              </ErrorBoundary>
            </div>
          </div>
        )}

        {/* ═══════ Trades ══════════════════════════════════════ */}
        {view === "trades" && (
          <div className="flex flex-col flex-1 min-h-0">
            <ViewHeader title="Trades" />
            <div className="flex-1 overflow-auto">
              <div className="p-5 space-y-4 max-w-[1200px] mx-auto">
                {/* Quick order */}
                <div className="rounded-lg bg-surface border border-border overflow-hidden">
                  <PanelHeader title={`Quick Order — ${symbol} · ${exchange}`} />
                  <ErrorBoundary label="Trade">
                    <TradePanel symbol={symbol} exchange={exchange} />
                  </ErrorBoundary>
                </div>
                {/* Positions */}
                <div className="rounded-lg bg-surface border border-border overflow-hidden">
                  <PanelHeader title="Open Positions" />
                  <ErrorBoundary label="Positions">
                    <PositionsPanel />
                  </ErrorBoundary>
                </div>
                {/* Orders */}
                <div className="rounded-lg bg-surface border border-border overflow-hidden">
                  <PanelHeader title="Order History" />
                  <ErrorBoundary label="Orders">
                    <OrdersPanel />
                  </ErrorBoundary>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ═══════ Signals ═════════════════════════════════════ */}
        {view === "signals" && (
          <div className="flex flex-col flex-1 min-h-0">
            <ErrorBoundary label="Symbol Bar">
              <SymbolBar
                symbol={symbol}
                exchange={exchange}
                interval={interval}
                onSymbolChange={handleSymbolChange}
                onIntervalChange={setIntervalStore}
              />
            </ErrorBoundary>
            <div className="flex-1 overflow-auto p-5">
              <div className="max-w-2xl mx-auto">
                <div className="rounded-lg bg-surface border border-border overflow-hidden">
                  <ErrorBoundary label="Signals">
                    <SignalPanel
                      symbol={symbol}
                      exchange={exchange}
                      candles={candles}
                      indicators={indicators}
                    />
                  </ErrorBoundary>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ═══════ Risk ════════════════════════════════════════ */}
        {view === "risk" && (
          <div className="flex flex-col flex-1 min-h-0">
            <ViewHeader title="Risk Management" />
            <div className="flex-1 overflow-auto p-5">
              <div className="max-w-2xl mx-auto">
                <div className="rounded-lg bg-surface border border-border overflow-hidden">
                  <ErrorBoundary label="Risk">
                    <RiskPanel />
                  </ErrorBoundary>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ═══════ Portfolio ═══════════════════════════════════ */}
        {view === "portfolio" && (
          <div className="flex flex-col flex-1 min-h-0">
            <ViewHeader title="Portfolio" />
            <div className="flex-1 overflow-auto p-5">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 max-w-[1200px] mx-auto">
                <div className="rounded-lg bg-surface border border-border overflow-hidden">
                  <PanelHeader title="Funds & Margin" />
                  <ErrorBoundary label="Funds">
                    <FundsPanel />
                  </ErrorBoundary>
                </div>
                <div className="rounded-lg bg-surface border border-border overflow-hidden">
                  <PanelHeader title="Watchlist" />
                  <ErrorBoundary label="Watchlist">
                    <WatchlistPanel ticks={{}} onSelect={handleSymbolChange} />
                  </ErrorBoundary>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ═══════ Performance ═════════════════════════════════ */}
        {view === "performance" && (
          <ErrorBoundary label="Performance">
            <PerformanceView />
          </ErrorBoundary>
        )}

        {/* ═══════ Assets ════════════════════════════════════ */}
        {view === "assets" && (
          <ErrorBoundary label="Assets">
            <AssetsView />
          </ErrorBoundary>
        )}

        {/* ═══════ Asset Detail ═══════════════════════════════ */}
        {view === "asset-detail" && (
          <ErrorBoundary label="Asset Detail">
            <AssetDetailView
              symbol={symbol}
              exchange={exchange}
              onBack={() => setView("dashboard")}
              onNavigate={(v) => setView(v as ViewId)}
            />
          </ErrorBoundary>
        )}

        {/* ═══════ Settings ════════════════════════════════════ */}
        {view === "settings" && (
          <ErrorBoundary label="Settings">
            <SettingsView />
          </ErrorBoundary>
        )}
      </div>
    </div>
  );
}

/* ── tiny shared subcomponents ──────────────────────────── */

function ViewHeader({ title }: { title: string }) {
  return (
    <div className="flex items-center px-6 h-11 border-b border-border shrink-0">
      <h1 className="text-[13px] font-semibold text-foreground tracking-tight">{title}</h1>
    </div>
  );
}

function PanelHeader({ title }: { title: string }) {
  return (
    <div className="px-4 py-2 border-b border-border">
      <span className="text-[11px] font-semibold text-foreground tracking-tight">{title}</span>
    </div>
  );
}
