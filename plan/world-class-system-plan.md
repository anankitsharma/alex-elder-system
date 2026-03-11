# World-Class Elder Trading System — Architecture Plan

**Date:** 2026-03-11
**Goal:** Transform our functional Elder trading system into a world-class, production-grade platform comparable to NautilusTrader, OpenBB, and institutional trading terminals.

---

## 1. Current State Assessment

Our system is **functionally complete** (~90%) but lacks the architectural sophistication and UI polish of world-class systems.

| Component | Status | LOC | World-Class Gap |
|-----------|--------|-----|-----------------|
| Indicators (5/5) | COMPLETE | 1,589 | Need incremental/streaming mode for live |
| Strategy/Signals | COMPLETE | 227 | Need event-driven pub/sub, more confirmations |
| Risk Management | COMPLETE | 444 | Need portfolio-level + circuit breakers |
| Trading Executor | COMPLETE | 648 | Need order reconciliation, fill tracking |
| Broker Integration | COMPLETE | 712 | Need reconnection resilience, rate limiting |
| API Endpoints (15) | COMPLETE | 905 | Need WebSocket streaming for all data |
| Scanner | COMPLETE | 306 | Need incremental scanning, not batch-only |
| Backtest Engine | COMPLETE | 543 | Need reality modeling (slippage, fees) |
| Data Validation | COMPLETE | 300 | Good as-is |
| Error Recovery | COMPLETE | 255 | Good as-is |
| Frontend Dashboard | BASIC | 2,303 | **Major upgrade needed** (see below) |
| Tests (169) | COMPLETE | 1,842 | Need E2E tests for new features |
| **TOTAL** | | **8,831** | |

### What's Missing for World-Class

1. **Frontend** — Basic panels only, no configurable layout, no analytics pages, no settings UI, no trade journal view, no performance dashboard
2. **Event Bus** — No internal pub/sub; components call each other directly
3. **Real-time Pipeline** — Indicators recalculate full history on every request; no incremental mode
4. **Configuration UI** — All settings are hardcoded or .env; nothing configurable from dashboard
5. **Notifications** — No Telegram/email alerts
6. **Performance Analytics** — Trade model exists but no analytics engine or visualization
7. **SEBI Compliance** — New regulations effective April 2026 require audit trails, rate limiting, static IP

---

## 2. Research Findings Summary

### Best Trading Backends (What the Best Systems Do)

| System | Key Innovation | Stars |
|--------|---------------|-------|
| **NautilusTrader** | Event-driven kernel, Rust core, nanosecond timestamps, fail-fast, backtest-live parity | 4k+ |
| **Freqtrade** | Polling-loop simplicity, FreqAI ML integration, huge community | 35k+ |
| **vnpy** | EventEngine pub/sub, OmsEngine in-memory cache, gateway abstraction | 27k+ |
| **LEAN (QuantConnect)** | Reality modeling layer (slippage, fees, margin), handler plugin system | 14k+ |
| **CCXT** | Unified API across 100+ exchanges, adapter pattern | 35k+ |
| **OpenAlgo** | Indian markets, unified broker API, React 19 rewrite, visual flow builder | Growing |

### Key Architecture Patterns to Adopt

1. **Event Bus (vnpy pattern)**: Central `EventEngine` with typed events (TICK, SIGNAL, ORDER, FILL, RISK) — decouple all components
2. **In-Memory Cache (vnpy OmsEngine)**: O(1) lookups for positions, orders, ticks — critical for real-time
3. **Gateway Abstraction (CCXT pattern)**: Broker-independent interface — future-proofs for Zerodha, Dhan, etc.
4. **Order State Machine**: NEW → SUBMITTED → ACCEPTED → FILLED/REJECTED/CANCELLED with reconciliation
5. **Layered Risk**: Pre-trade validation → Portfolio checks → Dynamic regime detection → Circuit breakers
6. **Incremental Indicators**: Batch for warmup, then O(1) per tick for live (talipp pattern)
7. **Configuration-Driven**: All parameters in DB/JSON, hot-reloadable, editable from UI

### Best Trading UIs

| Project | Key UI Pattern | Stack |
|---------|---------------|-------|
| **Bloomberg Terminal Clone** | Keyboard-first, SPA, terminal aesthetic | Next.js 15, React 19, Tailwind |
| **Deltalytix** | Drag-and-drop widgets, Zustand state | Next.js App Router, Radix UI |
| **OpenAlgo** | Visual flow builder, WebSocket integration | React 19, DaisyUI, TradingView |
| **shadcn-admin** | Cmd+K command palette, collapsible sidebar | shadcn/ui, Vite, React |
| **Tremor** | 35+ dashboard components, Tracker for streaks | React, Tailwind, Recharts |
| **React Grid Layout** | Draggable/resizable panels (Bloomberg-style) | React, 13.5k stars |

### Key UI Patterns to Adopt

1. **Configurable Layout**: React Grid Layout — drag panels, resize, save layout presets
2. **Command Palette**: Cmd+K — quick search symbols, switch pages, toggle settings
3. **Keyboard Shortcuts**: Buy/sell hotkeys, timeframe switching, indicator toggling
4. **Dark Mode First**: Trading UIs must be dark (eye strain during 6+ hour sessions)
5. **Real-time Everything**: WebSocket for ticks, signals, P&L, not polling
6. **Trade on Chart**: Entry/exit markers overlaid on candlestick charts
7. **Zustand State**: Lightweight, works perfectly with WebSocket streams

---

## 3. World-Class Architecture Design

### 3.1 Backend Architecture (Event-Driven Upgrade)

```
┌──────────────────────────────────────────────────────────────────┐
│                        FastAPI Server                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │ REST API │  │WebSocket │  │ Scheduler│  │  Startup/Lifespan│ │
│  │ /api/*   │  │ /ws/*    │  │ APSched  │  │  Login, Init DB  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘ │
│       │              │             │                  │           │
│  ┌────▼──────────────▼─────────────▼──────────────────▼────────┐ │
│  │                     EVENT BUS (New)                          │ │
│  │  Events: TICK, CANDLE, INDICATOR, SIGNAL, ORDER, FILL,      │ │
│  │          POSITION, RISK, ALERT, CONFIG_CHANGE, SYSTEM       │ │
│  │  Pattern: pub/sub with typed handlers                       │ │
│  └────┬──────┬──────┬──────┬──────┬──────┬──────┬─────────────┘ │
│       │      │      │      │      │      │      │               │
│  ┌────▼──┐┌──▼───┐┌─▼────┐┌▼─────┐┌─▼───┐┌─▼───┐┌▼──────────┐ │
│  │Broker ││Data  ││Indic-││Signal││Risk  ││Trade││Notifier   │ │
│  │Gateway││Engine││ators ││Engine││Engine││Exec ││(Telegram) │ │
│  └───────┘└──────┘└──────┘└──────┘└──────┘└─────┘└───────────┘ │
│       │                                              │           │
│  ┌────▼──────────────────────────────────────────────▼────────┐ │
│  │                    IN-MEMORY CACHE                          │ │
│  │  Ticks, Positions, Orders, Indicators, Config, Risk State  │ │
│  └────┬───────────────────────────────────────────────────────┘ │
│       │                                                         │
│  ┌────▼───────────────────────────────────────────────────────┐ │
│  │                    DATABASE (SQLAlchemy)                     │ │
│  │  Candles, Signals, Orders, Trades, Config, PortfolioRisk   │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### New Backend Components to Build

#### 1. Event Bus (`backend/app/core/event_bus.py`)
```python
class EventType(Enum):
    TICK = "tick"
    CANDLE_CLOSED = "candle_closed"
    INDICATOR_UPDATED = "indicator_updated"
    SIGNAL_GENERATED = "signal_generated"
    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILLED = "order_filled"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    RISK_ALERT = "risk_alert"
    CONFIG_CHANGED = "config_changed"
    SYSTEM_STATUS = "system_status"

class Event:
    type: EventType
    data: dict
    timestamp: datetime
    source: str

class EventBus:
    subscribe(event_type, handler) -> None
    publish(event: Event) -> None
    # Async handlers, typed events, logging
```

#### 2. In-Memory Cache (`backend/app/core/cache.py`)
```python
class TradingCache:
    # O(1) lookups for everything
    ticks: dict[str, TickData]           # symbol -> latest tick
    positions: dict[str, Position]       # symbol -> open position
    orders: dict[str, Order]             # order_id -> order
    indicators: dict[str, dict]          # symbol:tf -> indicator values
    config: dict[str, Any]              # key -> config value
    risk_state: PortfolioRiskState       # current risk snapshot
```

#### 3. Enhanced WebSocket Hub (`backend/app/ws/hub.py`)
```python
# Single WebSocket endpoint with channel subscriptions
# Channels: ticks, signals, orders, positions, risk, system
# Client subscribes: {"action": "subscribe", "channels": ["ticks:RELIANCE", "signals", "positions"]}
# Server pushes: {"channel": "signals", "data": {...}}
```

#### 4. Configuration API (`backend/app/api/config.py`)
```python
# Full CRUD for all trading parameters
GET  /api/config                     # All config by category
GET  /api/config/{category}          # INDICATOR/RISK/BROKER/ALERT/SCANNER
PUT  /api/config/{key}               # Update single config
POST /api/config/reset/{category}    # Reset to defaults
GET  /api/config/presets             # Saved config presets
POST /api/config/presets             # Save current as preset
```

#### 5. Performance Analytics (`backend/app/analytics/`)
```python
# Trade analytics engine
GET /api/analytics/overview          # Total P&L, win rate, Sharpe, max DD
GET /api/analytics/daily             # Daily P&L breakdown
GET /api/analytics/monthly           # Monthly performance grid
GET /api/analytics/by-symbol         # Per-symbol performance
GET /api/analytics/by-strategy       # Per-strategy performance
GET /api/analytics/equity-curve      # Equity curve data points
GET /api/analytics/drawdown          # Drawdown chart data
GET /api/analytics/distribution      # P&L distribution histogram
GET /api/analytics/r-multiples       # R-multiple analysis
GET /api/analytics/time-analysis     # Best/worst trading hours/days
GET /api/analytics/streaks           # Win/loss streak analysis
```

#### 6. Notification System (`backend/app/notifications/`)
```python
# Multi-channel notifications
POST /api/notifications/test         # Test notification
PUT  /api/notifications/settings     # Configure channels
# Channels: Telegram, Browser Push, Sound alerts
# Events: Signal generated, Order filled, Stoploss hit, Risk limit, Daily summary
```

---

### 3.2 Frontend Architecture (Complete Redesign)

```
┌────────────────────────────────────────────────────────────────────┐
│                     Next.js App Router                              │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Layout: Sidebar + Header + Main Content                     │  │
│  │  ┌─────────┐ ┌────────────────────────────────────────────┐  │  │
│  │  │Sidebar  │ │ Header: Symbol | Status | Mode | Search    │  │  │
│  │  │(collaps)│ ├────────────────────────────────────────────┤  │  │
│  │  │         │ │                                            │  │  │
│  │  │Dashboard│ │  Main Area (React Grid Layout)             │  │  │
│  │  │Charts   │ │  ┌──────────┐ ┌──────────┐ ┌──────────┐   │  │  │
│  │  │Scanner  │ │  │ Widget 1 │ │ Widget 2 │ │ Widget 3 │   │  │  │
│  │  │Backtest │ │  │(Chart)   │ │(MACD)    │ │(Signals) │   │  │  │
│  │  │Journal  │ │  └──────────┘ └──────────┘ └──────────┘   │  │  │
│  │  │Analytics│ │  ┌──────────┐ ┌─────────────────────────┐  │  │  │
│  │  │Risk     │ │  │ Widget 4 │ │ Widget 5               │  │  │  │
│  │  │Settings │ │  │(Positions│ │ (Trade Panel / Orders)  │  │  │  │
│  │  │         │ │  └──────────┘ └─────────────────────────┘  │  │  │
│  │  └─────────┘ └────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  State: Zustand stores (market, portfolio, settings, layout)       │
│  Data: WebSocket (real-time) + SWR (REST fallback)                 │
│  UI: shadcn/ui + Tremor + TradingView Lightweight Charts           │
└────────────────────────────────────────────────────────────────────┘
```

### Frontend Pages (8 total)

#### Page 1: Dashboard (`/`) — Command Center
- **Configurable widget grid** (React Grid Layout — drag, resize, save layouts)
- Available widgets:
  - Candlestick Chart (with indicator overlays: EMA, SafeZone, impulse colors)
  - MACD Sub-chart (4-color histogram)
  - Force Index chart
  - Three-Screen View (trend/setup/entry timeframes)
  - Active Signals feed (real-time)
  - Positions table (live P&L)
  - Orders table
  - Quick Trade panel
  - Watchlist with sparklines
  - Risk gauge (portfolio heat)
  - Market status (pre-market/open/close)
  - Equity curve mini-chart
- **Layout presets**: "Trading", "Analysis", "Monitoring" — one-click switch
- **Keyboard shortcuts**: B=Buy, S=Sell, 1-6=timeframes, Ctrl+K=command palette

#### Page 2: Charts (`/charts`) — Deep Analysis
- Full-screen candlestick chart with all overlays
- Indicator panel (toggle each on/off with checkboxes):
  - EMA-13, EMA-22 (line overlays)
  - MACD histogram (sub-pane)
  - Force Index 2-day, 13-day (sub-pane)
  - SafeZone stops (dot overlays on chart)
  - Impulse System colors (candle body colors)
  - AutoEnvelope channels
  - Elder-Ray (Bull Power / Bear Power)
- Trade markers on chart (entry/exit arrows with P&L labels)
- Drawing tools (horizontal lines, trendlines, rectangles)
- Multi-chart layout: 1x1, 2x1, 2x2, 3-screen
- Time range selector: 1D, 5D, 1M, 3M, 6M, 1Y, All

#### Page 3: Scanner (`/scanner`) — Market Screening
- **Impulse Heatmap Grid**: Color-coded grid of NIFTY 50/100/200/500
  - Green = bullish impulse, Red = bearish, Blue = neutral
  - Grouped by sector (IT, Banking, Pharma, FMCG, Auto, etc.)
  - Click any cell → opens chart
- **Signal Table**: Ranked by score (0-100)
  - Columns: Symbol, Score, Direction, Impulse, FI Trend, EMA Position, SafeZone Distance, Volume
  - Filters: Min score, direction, impulse color, exchange (NSE/NFO/MCX)
  - Sort by any column
- **Scan Controls**: Universe selection, timeframe, auto-refresh interval
- **F&O Scanner Tab**: Active futures/options with Elder signals
- **MCX Scanner Tab**: Commodities (Gold, Silver, Crude, NatGas, Copper)

#### Page 4: Backtest (`/backtest`) — Strategy Testing
- **Setup Panel**:
  - Symbol/exchange selector
  - Date range picker
  - Strategy parameters (all indicator settings, entry/exit rules)
  - Initial capital, position sizing, fees
- **Results Dashboard**:
  - Equity curve chart with drawdown overlay
  - Performance metrics cards: Total return, Sharpe, Sortino, Max DD, Win Rate, Profit Factor, CAGR, Calmar
  - Trade table: entry/exit dates, direction, P&L, R-multiple, duration
  - Monthly returns heatmap (green/red grid)
  - P&L distribution histogram
  - Trade markers on price chart
- **Compare Mode**: Run multiple backtests, overlay equity curves
- **Parameter Optimization**: Grid search over indicator parameters

#### Page 5: Trade Journal (`/journal`) — Review & Learn
- **Calendar View**: Day-by-day grid, colored by daily P&L
- **Trade List**: Filterable table of all trades
  - Grade (A/B/C/D), P&L, R-multiple, setup type, notes
  - Click to expand → chart snapshot with entry/exit markers
- **Daily Review Editor**: Rich text (TipTap) with:
  - Pre-market plan
  - Trade notes per entry
  - Post-market review
  - Emotion/psychology tagging
  - Screenshot attachment
- **Tag System**: Custom tags for patterns (e.g., "breakout", "pullback", "divergence")
- **Statistics by Tag**: Win rate and expectancy per tag/pattern

#### Page 6: Performance Analytics (`/analytics`) — Deep Metrics
- **Overview Cards**: Total P&L, Win Rate, Profit Factor, Sharpe, Max Drawdown
- **Equity Curve**: Full history with benchmark overlay (NIFTY 50)
- **Drawdown Chart**: Underwater equity plot
- **Monthly Returns Grid**: Calendar heatmap of monthly P&L%
- **By Symbol**: Bar chart of P&L per symbol
- **By Time**: Best/worst hours, days of week, months
- **Win/Loss Streaks**: Tremor Tracker component showing consecutive wins/losses
- **R-Multiple Distribution**: Histogram of trade outcomes in R units
- **Risk-Adjusted Metrics**: Sharpe, Sortino, Calmar ratios over time
- **Rolling Performance**: 30/60/90-day rolling Sharpe, win rate

#### Page 7: Risk Dashboard (`/risk`) — Portfolio Safety
- **Risk Gauge**: Circular gauge showing current portfolio risk % (2%/6% rules)
- **Position Risk Table**: Each position's risk amount, % of portfolio, distance to stop
- **Exposure Breakdown**: Pie chart by sector, asset class (equity/F&O/MCX)
- **Correlation Matrix**: Heatmap of position correlations
- **Daily P&L Limit**: Progress bar showing realized loss vs 2% daily limit
- **Monthly Risk Budget**: 6% rule tracking with calendar visualization
- **Circuit Breaker Status**: Green/Yellow/Red based on drawdown levels
- **Margin Utilization**: Used vs available margin
- **Worst Case Scenario**: If all stops hit simultaneously

#### Page 8: Settings (`/settings`) — Full Configuration
- **Indicators Tab**: Every parameter editable
  - EMA periods (13, 22), MACD (12, 26, 9), Force Index length
  - SafeZone lookback, coefficient, progressive mode
  - Impulse System colors
  - Each with reset-to-default button
- **Strategy Tab**: Signal scoring weights, minimum score, cooldown period
- **Risk Tab**: Per-trade risk %, portfolio limit %, circuit breaker thresholds
- **Broker Tab**: API keys (masked), connection status, refresh session
- **Scanner Tab**: Universe selection, scan interval, filter presets
- **Notifications Tab**: Telegram bot token, notification preferences per event
- **Layout Tab**: Save/load dashboard layouts, widget defaults
- **Data Tab**: Data source priority, cache settings, history retention
- **System Tab**: Log level, API rate limits, timezone, dark/light theme

### Frontend Components to Build

```
frontend/src/
├── app/
│   ├── layout.tsx              # Root layout with sidebar
│   ├── page.tsx                # Dashboard (configurable grid)
│   ├── charts/page.tsx         # Deep analysis charts
│   ├── scanner/page.tsx        # Market scanner
│   ├── backtest/page.tsx       # Backtesting
│   ├── journal/page.tsx        # Trade journal
│   ├── analytics/page.tsx      # Performance analytics
│   ├── risk/page.tsx           # Risk dashboard
│   └── settings/page.tsx       # Configuration
│
├── components/
│   ├── layout/
│   │   ├── Sidebar.tsx         # Collapsible nav (shadcn)
│   │   ├── Header.tsx          # Symbol bar + status + search
│   │   ├── CommandPalette.tsx  # Cmd+K search (shadcn command)
│   │   └── WidgetGrid.tsx      # React Grid Layout wrapper
│   │
│   ├── chart/
│   │   ├── CandlestickChart.tsx    # Main chart (existing, enhance)
│   │   ├── MACDChart.tsx           # MACD sub-chart (existing)
│   │   ├── ForceIndexChart.tsx     # FI sub-chart (new)
│   │   ├── ElderRayChart.tsx       # Bull/Bear Power (new)
│   │   ├── ThreeScreenView.tsx     # Triple screen (existing, enhance)
│   │   ├── EquityCurve.tsx         # Equity line chart (new)
│   │   ├── DrawdownChart.tsx       # Underwater plot (new)
│   │   ├── TradeMarkers.tsx        # Entry/exit arrows on chart (new)
│   │   └── IndicatorToggles.tsx    # Checkbox panel for overlays (new)
│   │
│   ├── scanner/
│   │   ├── ImpulseHeatmap.tsx      # Color grid by sector (new)
│   │   ├── SignalTable.tsx         # Ranked signal results (new)
│   │   └── ScanControls.tsx        # Universe + filters (new)
│   │
│   ├── trading/
│   │   ├── QuickTrade.tsx          # Compact buy/sell widget (new)
│   │   ├── PositionsTable.tsx      # Open positions (existing, enhance)
│   │   ├── OrdersTable.tsx         # Active orders (existing, enhance)
│   │   └── TradeConfirmDialog.tsx  # Safety confirmation (new)
│   │
│   ├── analytics/
│   │   ├── KPICards.tsx            # P&L, win rate, Sharpe cards (new)
│   │   ├── MonthlyReturns.tsx     # Calendar heatmap (new)
│   │   ├── PnLDistribution.tsx    # Histogram (new)
│   │   ├── StreakTracker.tsx       # Win/loss streaks via Tremor (new)
│   │   ├── RollingMetrics.tsx     # Rolling Sharpe/win rate (new)
│   │   └── SymbolBreakdown.tsx    # Per-symbol performance (new)
│   │
│   ├── risk/
│   │   ├── RiskGauge.tsx          # Circular gauge (new)
│   │   ├── ExposureChart.tsx      # Sector/asset pie (new)
│   │   ├── CorrelationMatrix.tsx  # Position correlations (new)
│   │   └── CircuitBreaker.tsx     # Status indicator (new)
│   │
│   ├── journal/
│   │   ├── CalendarView.tsx       # Day grid colored by P&L (new)
│   │   ├── TradeReview.tsx        # Trade detail with chart (new)
│   │   ├── DailyEditor.tsx        # Rich text journal (new)
│   │   └── TagManager.tsx         # Custom tag CRUD (new)
│   │
│   ├── settings/
│   │   ├── IndicatorSettings.tsx  # All indicator params (new)
│   │   ├── StrategySettings.tsx   # Signal weights (new)
│   │   ├── RiskSettings.tsx       # Risk limits (new)
│   │   ├── BrokerSettings.tsx     # API keys, connection (new)
│   │   ├── NotificationSettings.tsx # Telegram, alerts (new)
│   │   └── LayoutSettings.tsx     # Save/load layouts (new)
│   │
│   └── ui/                       # shadcn/ui components
│       └── (generated via npx shadcn add ...)
│
├── stores/                       # Zustand stores
│   ├── useMarketStore.ts         # Ticks, candles, indicators
│   ├── usePortfolioStore.ts      # Positions, orders, P&L
│   ├── useSettingsStore.ts       # Config, preferences
│   ├── useLayoutStore.ts         # Widget grid state, presets
│   └── useNotificationStore.ts   # Alerts, notifications
│
├── hooks/
│   ├── useWebSocket.ts           # Enhanced WS with channels (existing, upgrade)
│   ├── useCandles.ts             # OHLCV data (existing)
│   ├── useIndicators.ts          # Indicator data (existing)
│   ├── useKeyboardShortcuts.ts   # Global hotkeys (new)
│   └── useTheme.ts               # Dark/light mode (new)
│
└── lib/
    ├── api.ts                    # REST client (existing, extend)
    ├── ws.ts                     # WebSocket client (new)
    └── utils.ts                  # Utilities (existing)
```

### New NPM Dependencies

```json
{
  "react-grid-layout": "^1.5.0",          // Draggable widget panels
  "zustand": "^5.0.0",                     // State management
  "recharts": "^2.15.0",                   // Analytics charts (equity curve, histogram)
  "@tremor/react": "^3.18.0",             // Dashboard components (KPI cards, tracker)
  "cmdk": "^1.0.0",                        // Command palette (Cmd+K)
  "@tiptap/react": "^2.10.0",             // Rich text editor for journal
  "@tiptap/starter-kit": "^2.10.0",       // TipTap extensions
  "date-fns": "^4.1.0",                   // Date formatting
  "next-themes": "^0.4.0",                // Dark/light mode
  "@radix-ui/react-dialog": "latest",     // Modals (via shadcn)
  "@radix-ui/react-tabs": "latest",       // Tabs (via shadcn)
  "@radix-ui/react-tooltip": "latest"     // Tooltips (via shadcn)
}
```

---

## 4. Implementation Roadmap

### Phase A: Backend Event Infrastructure (3 modules)

**Priority: HIGH — Foundation for everything else**

1. **Event Bus** (`core/event_bus.py`)
   - EventType enum, Event dataclass, EventBus class
   - Async handlers, logging, error isolation
   - All existing components publish events instead of direct calls

2. **In-Memory Cache** (`core/cache.py`)
   - TradingCache with O(1) lookups
   - Auto-populate from DB on startup
   - Update on events (TICK, ORDER, FILL, POSITION)

3. **WebSocket Hub** (`ws/hub.py`)
   - Single `/ws/trading` endpoint with channel subscriptions
   - Channels: ticks, signals, orders, positions, risk, system, config
   - Broadcast events from EventBus to subscribed clients
   - Replace current simple `/ws/market` endpoint

### Phase B: Frontend Complete Redesign (8 pages)

**Priority: HIGH — User-facing transformation**

1. **Scaffold**: Install new deps, set up Zustand stores, shadcn components, dark theme
2. **Layout Shell**: Sidebar + Header + Command Palette + Widget Grid
3. **Dashboard Page** (`/`): Configurable widget grid with all trading widgets
4. **Charts Page** (`/charts`): Full-screen analysis with indicator toggles
5. **Scanner Page** (`/scanner`): Impulse heatmap + signal table
6. **Settings Page** (`/settings`): All configuration tabs
7. **Analytics Page** (`/analytics`): Performance metrics + equity curve
8. **Risk Page** (`/risk`): Portfolio risk dashboard
9. **Backtest Page** (`/backtest`): Setup + results visualization
10. **Journal Page** (`/journal`): Calendar + review + rich text editor

### Phase C: Backend Enhancements (5 modules)

**Priority: MEDIUM — Enables advanced features**

1. **Configuration API** (`api/config.py`)
   - Full CRUD for all trading parameters
   - Presets (save/load named configurations)
   - Publish CONFIG_CHANGED events

2. **Analytics Engine** (`analytics/engine.py`)
   - Compute all performance metrics from Trade model
   - Daily/monthly/by-symbol/by-strategy breakdowns
   - Rolling metrics over configurable windows

3. **Notification System** (`notifications/telegram.py`)
   - Telegram bot integration (python-telegram-bot)
   - Event-driven: subscribe to SIGNAL, ORDER_FILLED, RISK_ALERT
   - Browser push notifications via WebSocket

4. **Enhanced Scanner** (`scanner/live_scanner.py`)
   - Incremental scanning on tick events
   - Parallel symbol processing (asyncio.gather)
   - Sector grouping for heatmap data

5. **Backtest Reality Layer** (`backtest/reality.py`)
   - Slippage modeling (fixed + volume-based)
   - Fee modeling (brokerage + exchange + taxes)
   - Partial fill simulation
   - Multiple fill models (immediate, VWAP, TWAP)

### Phase D: Advanced Features (4 modules)

**Priority: LOW — Polish and sophistication**

1. **Portfolio-Level Risk Engine** (`risk/portfolio.py`)
   - Correlation analysis between positions
   - Sector exposure limits
   - Max portfolio notional
   - Dynamic position sizing (ATR-adjusted)
   - Market regime detection (volatility percentile)

2. **Order Reconciliation** (`trading/reconciliation.py`)
   - Sync local order state with Angel One
   - Detect missed fills
   - Handle partial fills
   - Audit trail for compliance

3. **Incremental Indicators** (`indicators/streaming.py`)
   - O(1) EMA update from last value + new price
   - O(1) MACD update
   - Streaming Force Index
   - Batch warmup + incremental live mode

4. **Trade Journal AI** (`analytics/journal_ai.py`)
   - Auto-generate trade review notes from signals + price action
   - Pattern recognition on historical trades
   - Suggest improvements based on journal tags

---

## 5. Technology Decisions

### Backend Stack (Confirmed + New)

| Package | Purpose | Status |
|---------|---------|--------|
| FastAPI | REST API + WebSocket | Existing |
| SQLAlchemy + aiosqlite | Async database | Existing |
| smartapi-python | Angel One broker | Existing |
| pandas + numpy | Data processing | Existing |
| loguru | Logging | Existing |
| apscheduler | Scheduled tasks | Existing |
| **python-telegram-bot** | Telegram notifications | **NEW** |
| **redis** | Event bus persistence (optional) | **NEW (optional)** |

### Frontend Stack (Confirmed + New)

| Package | Purpose | Status |
|---------|---------|--------|
| Next.js 16 + React 19 | Framework | Existing |
| TradingView Lightweight Charts 5 | Candlestick charts | Existing |
| Tailwind CSS 4 | Styling | Existing |
| **shadcn/ui** | UI components | **Needs full setup** |
| **Tremor** | Dashboard analytics components | **NEW** |
| **Zustand** | State management | **NEW** |
| **React Grid Layout** | Configurable panels | **NEW** |
| **cmdk** | Command palette | **NEW** |
| **Recharts** | Analytics charts | **NEW** |
| **next-themes** | Dark/light mode | **NEW** |
| **@tiptap/react** | Journal rich text editor | **NEW** |

---

## 6. What Makes This World-Class

### vs Current System
| Aspect | Current | World-Class Target |
|--------|---------|-------------------|
| Layout | Fixed panels | Drag-and-drop configurable grid |
| Navigation | Tab buttons | Sidebar + Cmd+K command palette |
| Real-time | WebSocket ticks only | All data streamed (signals, P&L, risk) |
| Configuration | .env file | Full UI with presets |
| Analytics | None | 10+ metric views, equity curve, monthly grid |
| Risk Visibility | None | Dedicated risk dashboard with gauge |
| Journal | None | Calendar + rich text + tag system |
| Scanner | Basic endpoint | Impulse heatmap + ranked table |
| Backtest | Engine exists | Full UI with equity curve, trade markers |
| Theme | Light only | Dark-first with toggle |
| Shortcuts | None | Full keyboard shortcuts |
| Notifications | None | Telegram + browser push |
| Architecture | Direct calls | Event-driven pub/sub |

### vs Industry Leaders
| Feature | Our System | NautilusTrader | Freqtrade | Bloomberg |
|---------|-----------|----------------|-----------|-----------|
| Elder Methodology | Native | No | No | No |
| Indian Markets | Native | Partial | No | Yes |
| Paper/Live Toggle | Yes | Yes | Yes | No |
| Configurable UI | React Grid | Terminal | FreqUI | Yes |
| Event-Driven | Planned | Yes | No (polling) | Yes |
| Backtest-Live Parity | Planned | Yes | Partial | N/A |
| Open Source | Yes | Yes | Yes | No |
| Signal Scoring | 0-100 | No | No | No |
| Trade Grading | A-D | No | No | No |

---

## 7. SEBI Compliance Checklist (April 2026)

- [ ] Audit trail: All orders logged with timestamps (our Trade model handles this)
- [ ] Rate limiting: Already implemented (60 req/min general, 10 orders/min)
- [ ] Order reconciliation: Needs implementation (Phase D)
- [ ] Static IP: Deployment consideration
- [ ] 5-year data retention: Database retention policy needed
- [ ] Algo registration: Register with NSE/BSE if >10 orders/sec
- [ ] 2FA: Already using TOTP for Angel One

---

## 8. File Counts Estimate

| Area | New Files | Existing (Modified) | Total |
|------|-----------|-------------------|-------|
| Backend core (event bus, cache) | 3 | 2 | 5 |
| Backend API (config, analytics, notifications) | 6 | 1 | 7 |
| Backend enhancements (scanner, backtest, risk) | 4 | 3 | 7 |
| Frontend pages | 7 | 1 | 8 |
| Frontend components | 30+ | 5 | 35+ |
| Frontend stores/hooks | 7 | 3 | 10 |
| Tests | 8+ | 2 | 10+ |
| **TOTAL** | **~65** | **~17** | **~82** |

Estimated new LOC: ~8,000-12,000 (roughly doubling the codebase)
