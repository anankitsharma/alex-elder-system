"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  fetchAllSettings,
  updateSetting,
  addToWatchlist,
  removeFromWatchlist,
  fetchInstruments,
  refreshSession,
  resetPaperAccount,
  type AllSettings,
  type WatchlistEntry,
  type TimeframeConfig,
  type RiskSettings,
  type DisplaySettings,
  type InstrumentData,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Search,
  X,
  Plus,
  Save,
  Loader2,
  RefreshCw,
  Trash2,
  ChevronDown,
  Check,
  AlertTriangle,
  Clock,
  Shield,
  BarChart3,
  Eye,
  Monitor,
  Settings2,
} from "lucide-react";

/* ── constants ─────────────────────────────────────── */

const TIMEFRAMES = [
  { value: "1w", label: "Weekly" },
  { value: "1d", label: "Daily" },
  { value: "4h", label: "4 Hour" },
  { value: "1h", label: "1 Hour" },
  { value: "15m", label: "15 Min" },
  { value: "5m", label: "5 Min" },
  { value: "1m", label: "1 Min" },
];

const ASSET_CLASSES = [
  { key: "EQUITY", label: "Equities", desc: "RELIANCE, TCS, INFY..." },
  { key: "INDEX_FO", label: "Index F&O", desc: "NIFTY, BANKNIFTY..." },
  { key: "COMMODITY", label: "Commodities", desc: "GOLD, CRUDE, SILVER..." },
  { key: "DEFAULT", label: "Default", desc: "Fallback for other assets" },
];

const SCREEN_LABELS = [
  { key: "screen1", label: "Screen 1 — Tide", desc: "Long-term trend" },
  { key: "screen2", label: "Screen 2 — Wave", desc: "Oscillator signals" },
  { key: "screen3", label: "Screen 3 — Ripple", desc: "Precision entry" },
];

/* ── section wrapper ───────────────────────────────── */

function Section({
  icon: Icon,
  title,
  desc,
  children,
}: {
  icon: typeof Shield;
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg bg-surface border border-border overflow-hidden">
      <div className="px-5 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-accent" />
          <h2 className="text-[13px] font-semibold text-foreground">{title}</h2>
        </div>
        <p className="text-[10px] text-muted mt-0.5">{desc}</p>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

/* ── toggle switch ─────────────────────────────────── */

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex items-center justify-between py-1.5 cursor-pointer group">
      <span className="text-[11px] text-foreground group-hover:text-accent transition-colors">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative w-8 h-[18px] rounded-full transition-colors duration-200",
          checked ? "bg-accent" : "bg-border"
        )}
      >
        <span
          className={cn(
            "absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-transform duration-200",
            checked ? "left-[16px]" : "left-[2px]"
          )}
        />
      </button>
    </label>
  );
}

/* ── select dropdown ───────────────────────────────── */

function Select({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full appearance-none bg-surface-2 border border-border rounded-md px-3 py-1.5 text-[11px] font-mono text-foreground focus:outline-none focus:border-accent pr-7 cursor-pointer"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-muted pointer-events-none" />
    </div>
  );
}

/* ── 3-state asset switcher: INACTIVE → PAPER → LIVE ── */

type AssetState = "INACTIVE" | "PAPER" | "LIVE";

const STATE_CONFIG: Record<AssetState, { label: string; bg: string; text: string; dot: string }> = {
  INACTIVE: { label: "Inactive", bg: "bg-zinc-800", text: "text-zinc-400", dot: "bg-zinc-500" },
  PAPER:    { label: "Paper",    bg: "bg-amber-500/20", text: "text-amber-400", dot: "bg-amber-500" },
  LIVE:     { label: "Live",     bg: "bg-red-500/20", text: "text-red-400", dot: "bg-red-500" },
};

const STATES: AssetState[] = ["INACTIVE", "PAPER", "LIVE"];

function ThreeStateSwitcher({
  state,
  onChange,
  liveDisabled = false,
}: {
  state: AssetState;
  onChange: (s: AssetState) => void;
  liveDisabled?: boolean;
}) {
  return (
    <div className="flex items-center rounded-md border border-border overflow-hidden">
      {STATES.map((s) => {
        const active = state === s;
        const disabled = s === "LIVE" && liveDisabled;
        const cfg = STATE_CONFIG[s];
        return (
          <button
            key={s}
            onClick={() => !disabled && onChange(s)}
            disabled={disabled}
            title={disabled ? "LIVE not approved — request from admin" : `Switch to ${s}`}
            className={cn(
              "px-2.5 py-1 text-[10px] font-semibold transition-all border-r border-border last:border-r-0",
              active ? `${cfg.bg} ${cfg.text}` : "bg-transparent text-muted/50 hover:text-muted",
              disabled && "opacity-30 cursor-not-allowed",
            )}
          >
            {active && <span className={cn("inline-block w-1.5 h-1.5 rounded-full mr-1.5", cfg.dot)} />}
            {cfg.label}
          </button>
        );
      })}
    </div>
  );
}

function WatchlistRow({
  item,
  onRemove,
}: {
  item: WatchlistEntry;
  onRemove: () => void;
}) {
  const [state, setState] = useState<AssetState>("INACTIVE");
  const [loading, setLoading] = useState(false);

  // Load current state on mount
  useEffect(() => {
    (async () => {
      try {
        // Check if pipeline is active for this symbol
        const res = await fetch(
          `http://localhost:8000/api/strategy/pipeline/command-center`,
          { headers: { Authorization: `Bearer ${localStorage.getItem("elder_token") || ""}` } },
        );
        if (res.ok) {
          const data = await res.json();
          const asset = data.assets?.find(
            (a: { symbol: string; exchange: string }) =>
              a.symbol === item.symbol && a.exchange === item.exchange
          );
          if (asset) {
            setState(asset.trading_mode === "LIVE" ? "LIVE" : "PAPER");
          } else {
            setState("INACTIVE");
          }
        }
      } catch {
        // ignore
      }
    })();
  }, [item.symbol, item.exchange]);

  const handleStateChange = async (newState: AssetState) => {
    setLoading(true);
    const token = localStorage.getItem("elder_token") || "";
    const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

    try {
      if (newState === "INACTIVE" && state !== "INACTIVE") {
        // Stop pipeline
        await fetch("http://localhost:8000/api/strategy/pipeline/stop", {
          method: "POST",
          headers,
          body: JSON.stringify({ symbol: item.symbol, exchange: item.exchange }),
        });
      } else if (newState !== "INACTIVE" && state === "INACTIVE") {
        // Start pipeline
        await fetch("http://localhost:8000/api/strategy/pipeline/start", {
          method: "POST",
          headers,
          body: JSON.stringify({ symbol: item.symbol, exchange: item.exchange }),
        });
      }

      if (newState === "PAPER" || newState === "LIVE") {
        // Set trading mode
        await fetch(
          `http://localhost:8000/api/strategy/pipeline/asset-settings/${item.symbol}`,
          {
            method: "PUT",
            headers,
            body: JSON.stringify({
              exchange: item.exchange,
              trading_mode: newState,
              user_id: 1,
            }),
          },
        );
      }

      setState(newState);
    } catch {
      // revert on error
    }
    setLoading(false);
  };

  return (
    <div className="flex items-center justify-between px-3 py-2 rounded-md hover:bg-surface-2/60 transition-colors group">
      <div className="flex items-center gap-2.5">
        <span className={cn("w-1.5 h-1.5 rounded-full", STATE_CONFIG[state].dot)} />
        <span className="text-[11px] font-medium text-foreground">{item.symbol}</span>
        <span className="text-[9px] px-1.5 py-0.5 rounded bg-surface-2 border border-border text-muted font-mono">
          {item.exchange}
        </span>
      </div>
      <div className="flex items-center gap-2">
        {loading ? (
          <Loader2 className="w-3 h-3 text-muted animate-spin" />
        ) : (
          <ThreeStateSwitcher
            state={state}
            onChange={handleStateChange}
            liveDisabled={false}
          />
        )}
        <button
          onClick={onRemove}
          className="p-1 rounded text-muted hover:text-red-500 hover:bg-red-500/10 transition-colors opacity-0 group-hover:opacity-100"
          title="Remove from watchlist"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}

/* ── main component ────────────────────────────────── */

export default function SettingsView() {
  const [settings, setSettings] = useState<AllSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<InstrumentData[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchExchange, setSearchExchange] = useState("NSE");
  const [confirmReset, setConfirmReset] = useState(false);
  const searchTimeout = useRef<ReturnType<typeof setTimeout>>(undefined);

  /* ── load settings ──────────────────────────────── */

  const load = useCallback(async () => {
    try {
      const data = await fetchAllSettings();
      setSettings(data);
    } catch {
      // Use defaults if backend unavailable
      setSettings({
        watchlist: [],
        timeframes: {
          EQUITY: { screen1: "1w", screen2: "1d", screen3: "1h" },
          INDEX_FO: { screen1: "1d", screen2: "1h", screen3: "15m" },
          COMMODITY: { screen1: "1d", screen2: "1h", screen3: "15m" },
          DEFAULT: { screen1: "1d", screen2: "4h", screen3: "1h" },
        },
        risk: { max_risk_per_trade_pct: 2.0, max_portfolio_risk_pct: 6.0, min_signal_score: 65 },
        display: {
          default_symbol: "NIFTY",
          default_exchange: "NFO",
          default_interval: "1d",
          show_volume: true,
          show_macd: true,
          show_force_index: true,
          show_elder_ray: true,
        },
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  /* ── save helper ────────────────────────────────── */

  const save = async (key: string, value: unknown) => {
    setSaving(key);
    try {
      await updateSetting(key, value);
      setSaved(key);
      setTimeout(() => setSaved(null), 1500);
    } catch {
      // silently fail — backend might be offline
    } finally {
      setSaving(null);
    }
  };

  /* ── search for instruments ─────────────────────── */

  const doSearch = useCallback(async (q: string, exch: string) => {
    if (q.length < 2) {
      setSearchResults([]);
      return;
    }
    setSearchLoading(true);
    try {
      const res = await fetchInstruments(exch, q, 12);
      setSearchResults(res.instruments ?? []);
    } catch {
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  }, []);

  const handleSearchInput = (q: string) => {
    setSearchQuery(q);
    clearTimeout(searchTimeout.current);
    searchTimeout.current = setTimeout(() => doSearch(q, searchExchange), 300);
  };

  /* ── watchlist add/remove ───────────────────────── */

  const handleAdd = async (sym: string, exch: string) => {
    if (!settings) return;
    try {
      const res = await addToWatchlist(sym, exch);
      if (res.watchlist) {
        setSettings({ ...settings, watchlist: res.watchlist });
      }
    } catch {
      // Optimistic add on failure
      const newWl = [...settings.watchlist, { symbol: sym, exchange: exch }];
      setSettings({ ...settings, watchlist: newWl });
    }
    setSearchQuery("");
    setSearchResults([]);
  };

  const handleRemove = async (sym: string, exch: string) => {
    if (!settings) return;
    const newWl = settings.watchlist.filter(
      (w) => !(w.symbol === sym && w.exchange === exch)
    );
    setSettings({ ...settings, watchlist: newWl });
    try {
      await removeFromWatchlist(sym, exch);
    } catch {
      // Already updated optimistically
    }
  };

  /* ── timeframe update ───────────────────────────── */

  const updateTimeframe = (assetClass: string, screen: string, value: string) => {
    if (!settings) return;
    const tf = { ...settings.timeframes };
    tf[assetClass] = { ...tf[assetClass], [screen]: value };
    setSettings({ ...settings, timeframes: tf });
    save("timeframes", tf);
  };

  /* ── risk update ────────────────────────────────── */

  const updateRisk = (field: keyof RiskSettings, value: number) => {
    if (!settings) return;
    const r = { ...settings.risk, [field]: value };
    setSettings({ ...settings, risk: r });
    save("risk", r);
  };

  /* ── display update ─────────────────────────────── */

  const updateDisplay = (field: keyof DisplaySettings, value: boolean | string) => {
    if (!settings) return;
    const d = { ...settings.display, [field]: value };
    setSettings({ ...settings, display: d });
    save("display", d);
  };

  /* ── system actions ─────────────────────────────── */

  const handleRefreshSession = async () => {
    try {
      await refreshSession();
    } catch {
      // ignore
    }
  };

  const handleResetPaper = async () => {
    try {
      await resetPaperAccount();
      setConfirmReset(false);
    } catch {
      // ignore
    }
  };

  /* ── render ─────────────────────────────────────── */

  if (loading || !settings) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="w-5 h-5 text-muted animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex items-center px-6 h-11 border-b border-border shrink-0">
        <h1 className="text-[13px] font-semibold text-foreground tracking-tight">Settings</h1>
      </div>

      <div className="flex-1 overflow-auto">
        <div className="p-5 space-y-5 max-w-[900px] mx-auto">

          {/* ═══ Watchlist ═══════════════════════════════ */}
          <Section icon={BarChart3} title="Watchlist" desc="Manage tracked assets. Add or remove symbols from your watchlist.">
            {/* Search to add */}
            <div className="mb-4">
              <div className="flex gap-2 mb-1">
                <div className="relative flex-1">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => handleSearchInput(e.target.value)}
                    placeholder="Search symbol to add..."
                    className="w-full bg-surface-2 border border-border rounded-md pl-8 pr-3 py-1.5 text-[11px] text-foreground placeholder:text-muted focus:outline-none focus:border-accent"
                  />
                  {searchLoading && (
                    <Loader2 className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-muted animate-spin" />
                  )}
                </div>
                <div className="flex rounded-md overflow-hidden border border-border">
                  {["NSE", "NFO", "MCX"].map((ex) => (
                    <button
                      key={ex}
                      onClick={() => {
                        setSearchExchange(ex);
                        if (searchQuery.length >= 2) doSearch(searchQuery, ex);
                      }}
                      className={cn(
                        "px-2.5 py-1.5 text-[10px] font-medium transition-colors",
                        searchExchange === ex
                          ? "bg-accent/15 text-accent"
                          : "bg-surface-2 text-muted hover:text-foreground"
                      )}
                    >
                      {ex}
                    </button>
                  ))}
                </div>
              </div>

              {/* Search results */}
              {searchResults.length > 0 && (
                <div className="border border-border rounded-md bg-surface-2 max-h-48 overflow-auto">
                  {searchResults.map((inst) => {
                    const inWl = settings.watchlist.some(
                      (w) => w.symbol === inst.symbol && w.exchange === inst.exch_seg
                    );
                    return (
                      <button
                        key={`${inst.symbol}-${inst.exch_seg}`}
                        onClick={() => !inWl && handleAdd(inst.symbol, inst.exch_seg)}
                        disabled={inWl}
                        className={cn(
                          "flex items-center justify-between w-full px-3 py-1.5 text-[11px] transition-colors border-b border-border/50 last:border-0",
                          inWl
                            ? "opacity-40 cursor-not-allowed"
                            : "hover:bg-surface cursor-pointer"
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-foreground">{inst.symbol}</span>
                          <span className="text-[9px] text-muted">{inst.name}</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-[9px] px-1 py-0.5 rounded bg-surface border border-border text-muted">
                            {inst.exch_seg}
                          </span>
                          {inWl ? (
                            <Check className="w-3 h-3 text-green" />
                          ) : (
                            <Plus className="w-3 h-3 text-accent" />
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Current watchlist */}
            <div className="space-y-0.5">
              {settings.watchlist.length === 0 ? (
                <div className="py-6 text-center text-[11px] text-muted">
                  No assets in watchlist. Search above to add.
                </div>
              ) : (
                settings.watchlist.map((item) => (
                  <WatchlistRow
                    key={`${item.symbol}-${item.exchange}`}
                    item={item}
                    onRemove={() => handleRemove(item.symbol, item.exchange)}
                  />
                ))
              )}
            </div>
          </Section>

          {/* ═══ Timeframes ═════════════════════════════ */}
          <Section icon={Clock} title="Screen Timeframes" desc="Configure which timeframe each screen uses per asset class (Elder's Triple Screen).">
            <div className="space-y-5">
              {ASSET_CLASSES.map(({ key, label, desc }) => (
                <div key={key}>
                  <div className="flex items-center gap-2 mb-2.5">
                    <span className="text-[11px] font-semibold text-foreground">{label}</span>
                    <span className="text-[9px] text-muted">{desc}</span>
                  </div>
                  <div className="grid grid-cols-3 gap-3">
                    {SCREEN_LABELS.map(({ key: sk, label: sl, desc: sd }) => (
                      <div key={sk}>
                        <label className="text-[10px] text-muted block mb-1">{sl}</label>
                        <Select
                          value={settings.timeframes[key]?.[sk as keyof TimeframeConfig] ?? "1d"}
                          options={TIMEFRAMES}
                          onChange={(v) => updateTimeframe(key, sk, v)}
                        />
                        <span className="text-[9px] text-muted mt-0.5 block">{sd}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {saving === "timeframes" && (
              <div className="flex items-center gap-1.5 mt-3 text-[10px] text-muted">
                <Loader2 className="w-3 h-3 animate-spin" /> Saving...
              </div>
            )}
            {saved === "timeframes" && (
              <div className="flex items-center gap-1.5 mt-3 text-[10px] text-green">
                <Check className="w-3 h-3" /> Saved
              </div>
            )}
          </Section>

          {/* ═══ Risk Parameters ════════════════════════ */}
          <Section icon={Shield} title="Risk Management" desc="Elder's 2% Rule (per-trade) and 6% Rule (monthly portfolio). These affect position sizing and circuit breaker.">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <label className="text-[10px] text-muted block mb-1">Max Risk Per Trade (%)</label>
                <input
                  type="number"
                  step="0.1"
                  min="0.1"
                  max="10"
                  value={settings.risk.max_risk_per_trade_pct}
                  onChange={(e) => updateRisk("max_risk_per_trade_pct", parseFloat(e.target.value) || 2)}
                  className="w-full bg-surface-2 border border-border rounded-md px-3 py-1.5 text-[11px] font-mono text-foreground focus:outline-none focus:border-accent"
                />
                <span className="text-[9px] text-muted mt-0.5 block">Elder recommends 2% max</span>
              </div>
              <div>
                <label className="text-[10px] text-muted block mb-1">Max Portfolio Risk / Month (%)</label>
                <input
                  type="number"
                  step="0.5"
                  min="1"
                  max="20"
                  value={settings.risk.max_portfolio_risk_pct}
                  onChange={(e) => updateRisk("max_portfolio_risk_pct", parseFloat(e.target.value) || 6)}
                  className="w-full bg-surface-2 border border-border rounded-md px-3 py-1.5 text-[11px] font-mono text-foreground focus:outline-none focus:border-accent"
                />
                <span className="text-[9px] text-muted mt-0.5 block">Elder recommends 6% max</span>
              </div>
              <div>
                <label className="text-[10px] text-muted block mb-1">Min Signal Score</label>
                <input
                  type="number"
                  step="5"
                  min="0"
                  max="100"
                  value={settings.risk.min_signal_score}
                  onChange={(e) => updateRisk("min_signal_score", parseInt(e.target.value) || 65)}
                  className="w-full bg-surface-2 border border-border rounded-md px-3 py-1.5 text-[11px] font-mono text-foreground focus:outline-none focus:border-accent"
                />
                <span className="text-[9px] text-muted mt-0.5 block">Minimum confidence to trade</span>
              </div>
            </div>

            {saving === "risk" && (
              <div className="flex items-center gap-1.5 mt-3 text-[10px] text-muted">
                <Loader2 className="w-3 h-3 animate-spin" /> Saving...
              </div>
            )}
            {saved === "risk" && (
              <div className="flex items-center gap-1.5 mt-3 text-[10px] text-green">
                <Check className="w-3 h-3" /> Saved
              </div>
            )}
          </Section>

          {/* ═══ Display Preferences ════════════════════ */}
          <Section icon={Eye} title="Chart Display" desc="Control which indicator sub-panes appear below the main price chart.">
            <div className="space-y-1">
              <Toggle
                checked={settings.display.show_volume}
                onChange={(v) => updateDisplay("show_volume", v)}
                label="Volume overlay"
              />
              <Toggle
                checked={settings.display.show_macd}
                onChange={(v) => updateDisplay("show_macd", v)}
                label="MACD (12, 26, 9)"
              />
              <Toggle
                checked={settings.display.show_force_index}
                onChange={(v) => updateDisplay("show_force_index", v)}
                label="Force Index (2, 13)"
              />
              <Toggle
                checked={settings.display.show_elder_ray}
                onChange={(v) => updateDisplay("show_elder_ray", v)}
                label="Elder-Ray (Bull/Bear Power)"
              />
            </div>

            <div className="border-t border-border mt-4 pt-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="text-[10px] text-muted block mb-1">Default Symbol</label>
                  <input
                    type="text"
                    value={settings.display.default_symbol}
                    onChange={(e) => updateDisplay("default_symbol", e.target.value.toUpperCase())}
                    className="w-full bg-surface-2 border border-border rounded-md px-3 py-1.5 text-[11px] font-mono text-foreground focus:outline-none focus:border-accent uppercase"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-muted block mb-1">Default Exchange</label>
                  <Select
                    value={settings.display.default_exchange}
                    options={[
                      { value: "NSE", label: "NSE" },
                      { value: "NFO", label: "NFO" },
                      { value: "MCX", label: "MCX" },
                    ]}
                    onChange={(v) => updateDisplay("default_exchange", v)}
                  />
                </div>
                <div>
                  <label className="text-[10px] text-muted block mb-1">Default Interval</label>
                  <Select
                    value={settings.display.default_interval}
                    options={TIMEFRAMES}
                    onChange={(v) => updateDisplay("default_interval", v)}
                  />
                </div>
              </div>
            </div>
          </Section>

          {/* ═══ System ═════════════════════════════════ */}
          <Section icon={Monitor} title="System" desc="Broker session management and paper trading controls.">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-[11px] font-medium text-foreground">Refresh Broker Session</div>
                  <div className="text-[10px] text-muted">Force re-login to Angel One APIs</div>
                </div>
                <button
                  onClick={handleRefreshSession}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-surface-2 border border-border text-[11px] text-foreground hover:border-accent hover:text-accent transition-colors"
                >
                  <RefreshCw className="w-3 h-3" />
                  Refresh
                </button>
              </div>

              <div className="border-t border-border pt-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-[11px] font-medium text-foreground">Reset Paper Account</div>
                    <div className="text-[10px] text-muted">Reset paper balance to ₹1,00,000 and clear all positions</div>
                  </div>
                  {!confirmReset ? (
                    <button
                      onClick={() => setConfirmReset(true)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-surface-2 border border-border text-[11px] text-red hover:bg-red/10 hover:border-red/30 transition-colors"
                    >
                      <Trash2 className="w-3 h-3" />
                      Reset
                    </button>
                  ) : (
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-amber flex items-center gap-1">
                        <AlertTriangle className="w-3 h-3" /> Are you sure?
                      </span>
                      <button
                        onClick={handleResetPaper}
                        className="px-3 py-1.5 rounded-md bg-red/15 border border-red/20 text-[11px] text-red font-medium hover:bg-red/25 transition-colors"
                      >
                        Confirm Reset
                      </button>
                      <button
                        onClick={() => setConfirmReset(false)}
                        className="px-3 py-1.5 rounded-md bg-surface-2 border border-border text-[11px] text-muted hover:text-foreground transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
