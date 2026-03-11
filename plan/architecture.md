# System Architecture

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js + React)                    │
│                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │Dashboard │ │Triple    │ │Scanner   │ │Backtest  │           │
│  │  Home    │ │ Screen   │ │          │ │          │           │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
│       │             │            │             │                 │
│  ┌────┴─────────────┴────────────┴─────────────┴─────┐          │
│  │              WebSocket + REST API Client            │          │
│  └─────────────────────┬─────────────────────────────┘          │
│                        │                                        │
└────────────────────────┼────────────────────────────────────────┘
                         │ WebSocket + HTTP
                         │
┌────────────────────────┼────────────────────────────────────────┐
│                  BACKEND (FastAPI + Python)                      │
│                        │                                        │
│  ┌─────────────────────┴─────────────────────────────┐          │
│  │              FastAPI Server (uvicorn)               │          │
│  │  ┌─────────────┐  ┌────────────┐  ┌────────────┐  │          │
│  │  │ REST Routes │  │  WS Routes │  │  Scheduler  │  │          │
│  │  └──────┬──────┘  └─────┬──────┘  └──────┬─────┘  │          │
│  └─────────┼───────────────┼────────────────┼────────┘          │
│            │               │                │                   │
│  ┌─────────┴───────────────┴────────────────┴────────┐          │
│  │                  Core Engine                        │          │
│  │                                                     │          │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │          │
│  │  │Indicator │  │ Signal   │  │ Risk Management  │  │          │
│  │  │ Engine   │  │ Engine   │  │                  │  │          │
│  │  │          │  │          │  │ • 2% Rule        │  │          │
│  │  │• Impulse │  │• Scoring │  │ • 6% Rule        │  │          │
│  │  │• Elder   │  │• Scanner │  │ • SafeZone Stops │  │          │
│  │  │  Ray     │  │• Filters │  │ • Circuit Breaker│  │          │
│  │  │• Force   │  │• Triple  │  │                  │  │          │
│  │  │  Index   │  │  Screen  │  │                  │  │          │
│  │  │• MACD-H  │  │          │  │                  │  │          │
│  │  │• SafeZone│  │          │  │                  │  │          │
│  │  │• AutoEnv │  │          │  │                  │  │          │
│  │  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │          │
│  └───────┼──────────────┼────────────────┼────────────┘          │
│          │              │                │                       │
│  ┌───────┴──────────────┴────────────────┴────────────┐          │
│  │              Trading Engine                         │          │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │          │
│  │  │  Paper   │  │   Live   │  │  Trade Journal   │  │          │
│  │  │  Trader  │  │ Executor │  │  + Grading       │  │          │
│  │  └──────────┘  └────┬─────┘  └──────────────────┘  │          │
│  └──────────────────────┼─────────────────────────────┘          │
│                         │                                       │
└─────────────────────────┼───────────────────────────────────────┘
                          │
              ┌───────────┴───────────┐
              │   Angel One SmartAPI   │
              │                        │
              │  • REST API (orders)   │
              │  • WebSocket (prices)  │
              │  • Historical data     │
              │  • Instrument master   │
              │                        │
              │  Exchanges:            │
              │  NSE (1) | NFO (2)     │
              │  BSE (3) | MCX (5)     │
              └────────────────────────┘
```

---

## Data Flow — Real-Time Pipeline

```
Angel One SmartWebSocketV2
    │
    │ Binary WebSocket frames (LTP/QUOTE/SNAP_QUOTE)
    │
    ▼
┌──────────────────────┐
│ WebSocket Consumer   │  asyncio task
│ (websocket_feed.py)  │  Parse binary → Python objects
└──────────┬───────────┘
           │
           │ asyncio.Queue
           │
           ▼
┌──────────────────────┐
│ Indicator Pipeline   │  pandas-ta + custom indicators
│ (pipeline.py)        │  OHLCV → EMA, MACD, FI, ER, Impulse
└──────────┬───────────┘
           │
           │ Computed indicators
           │
           ▼
┌──────────────────────┐
│ Signal Engine        │  Multi-confirmation scoring
│ (signals.py)         │  Filters → Score 0-100 → Signal
└──────────┬───────────┘
           │
           ├──────────────────────────┐
           │                          │
           ▼                          ▼
┌──────────────────┐      ┌──────────────────────┐
│ Risk Manager     │      │ FastAPI WebSocket     │
│ (2%/6% check)   │      │ → Frontend Charts     │
└────────┬─────────┘      └──────────────────────┘
         │
         │ If passes risk checks
         │
         ▼
┌──────────────────────┐
│ Trade Executor       │
│ Paper or Live mode   │
│ Angel One SmartAPI   │
└──────────────────────┘
```

---

## Database Schema (SQLite → PostgreSQL)

### instruments
```sql
CREATE TABLE instruments (
    id INTEGER PRIMARY KEY,
    token TEXT NOT NULL,           -- Angel One token
    symbol TEXT NOT NULL,          -- Trading symbol
    name TEXT,                     -- Company name
    exchange TEXT NOT NULL,        -- NSE, NFO, BSE, MCX
    segment TEXT,                  -- EQ, FUT, OPT, COM
    lot_size INTEGER DEFAULT 1,
    tick_size REAL DEFAULT 0.05,
    expiry DATE,                  -- For F&O/MCX
    strike REAL,                  -- For options
    option_type TEXT,             -- CE/PE
    updated_at TIMESTAMP
);
```

### candles
```sql
CREATE TABLE candles (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER REFERENCES instruments(id),
    timeframe TEXT NOT NULL,       -- 1m, 5m, 15m, 1h, 1d, 1w
    timestamp TIMESTAMP NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    UNIQUE(instrument_id, timeframe, timestamp)
);
```

### signals
```sql
CREATE TABLE signals (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER REFERENCES instruments(id),
    timestamp TIMESTAMP NOT NULL,
    direction TEXT NOT NULL,       -- LONG, SHORT
    score INTEGER NOT NULL,        -- 0-100 confidence
    strategy TEXT NOT NULL,        -- TRIPLE_SCREEN, IMPULSE, DIVERGENCE
    confirmations TEXT,            -- JSON array of active confirmations
    entry_price REAL,
    stop_price REAL,
    target_price REAL,
    status TEXT DEFAULT 'PENDING', -- PENDING, EXECUTED, EXPIRED, CANCELLED
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### orders
```sql
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    signal_id INTEGER REFERENCES signals(id),
    instrument_id INTEGER REFERENCES instruments(id),
    order_id TEXT,                 -- Angel One order ID
    direction TEXT NOT NULL,       -- BUY, SELL
    order_type TEXT NOT NULL,      -- MARKET, LIMIT, SL, SL-M
    quantity INTEGER NOT NULL,
    price REAL,
    trigger_price REAL,
    status TEXT DEFAULT 'PENDING', -- PENDING, OPEN, FILLED, CANCELLED, REJECTED
    mode TEXT NOT NULL,            -- PAPER, LIVE
    filled_price REAL,
    filled_quantity INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
```

### positions
```sql
CREATE TABLE positions (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER REFERENCES instruments(id),
    direction TEXT NOT NULL,       -- LONG, SHORT
    entry_price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    stop_price REAL,
    target_price REAL,
    current_price REAL,
    unrealized_pnl REAL,
    risk_amount REAL,             -- (entry - stop) × quantity
    risk_percent REAL,            -- risk_amount / equity × 100
    mode TEXT NOT NULL,            -- PAPER, LIVE
    status TEXT DEFAULT 'OPEN',    -- OPEN, CLOSED
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP
);
```

### trades (journal)
```sql
CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    position_id INTEGER REFERENCES positions(id),
    instrument_id INTEGER REFERENCES instruments(id),
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    pnl REAL NOT NULL,
    pnl_percent REAL,
    channel_width REAL,           -- AutoEnvelope width at entry
    grade TEXT,                   -- A, B, C, D (based on % of channel captured)
    grade_percent REAL,           -- (exit-entry)/(upper-lower) × 100
    strategy TEXT,
    signal_score INTEGER,
    notes TEXT,
    mode TEXT NOT NULL,
    entry_time TIMESTAMP,
    exit_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### config
```sql
CREATE TABLE config (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,           -- JSON value
    category TEXT NOT NULL,        -- INDICATOR, RISK, BROKER, ALERT, SCANNER
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### portfolio_risk
```sql
CREATE TABLE portfolio_risk (
    id INTEGER PRIMARY KEY,
    date DATE NOT NULL,
    month_start_equity REAL NOT NULL,
    current_equity REAL NOT NULL,
    total_open_risk REAL,          -- Sum of all position risks
    month_realized_losses REAL,    -- Cumulative losses this month
    total_risk_percent REAL,       -- (open_risk + losses) / month_start × 100
    is_halted BOOLEAN DEFAULT FALSE, -- TRUE when ≥ 6%
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Frontend Page Structure

### 1. Dashboard Home (`/`)
- KPI cards: Total P&L, Today's P&L, Win Rate, Risk Usage (6% gauge)
- Open positions table with live P&L
- Recent signals feed
- Equity curve chart
- Market status indicator (open/closed)

### 2. Triple Screen (`/triple-screen`)
- Symbol selector (search NIFTY 500 + F&O + MCX)
- Three synchronized chart panels:
  - Weekly: Candlestick + MACD-H + Impulse colors
  - Daily: Candlestick + Force Index + Elder-Ray + Impulse colors
  - Intraday (15m/1h): Candlestick + entry zone markers
- Signal status panel: Current trend, pullback status, entry readiness
- One-click order panel with auto-calculated position size

### 3. Scanner (`/scanner`)
- Scan controls: Select universe (NIFTY 50/200/500, F&O, MCX), timeframe
- Results table: Symbol, Impulse Color, Signal Score, Direction, Entry/Stop/Target
- Impulse heatmap grid (color-coded by sector)
- Filter by: Minimum score, direction, strategy type

### 4. Backtest (`/backtest`)
- Strategy selector (Triple Screen, Impulse, Divergence)
- Date range picker
- Symbol/universe selector
- Parameter tuning form
- Results: Equity curve, trade list, performance metrics table
- Chart with entry/exit markers

### 5. Trade Journal (`/journal`)
- Trade history table with grades
- Filter by date, symbol, strategy, grade
- Grade distribution chart
- Monthly P&L summary
- Individual trade details with chart snapshot

### 6. Risk Dashboard (`/risk`)
- 2% rule: Per-position risk breakdown
- 6% rule: Monthly gauge (visual progress bar)
- Position sizing calculator
- Drawdown chart
- Circuit breaker status

### 7. Settings (`/settings`)
- **Broker**: Angel One API key, client ID, TOTP secret (encrypted)
- **Indicators**: All Elder indicator parameters (EMA periods, MACD params, SafeZone factor, etc.)
- **Risk**: 2% limit, 6% limit, max positions, min volume threshold
- **Signals**: Minimum confidence score, cooldown period, enabled strategies
- **Alerts**: Enable/disable, notification preferences
- **Trading Mode**: Paper/Live toggle with confirmation

---

## Security Considerations

1. **API Keys**: Store Angel One credentials encrypted in DB, never in frontend
2. **TOTP Secret**: Server-side only, generate TOTP on backend
3. **Live Trading Safeguards**:
   - Paper mode by default
   - Confirmation dialog for switching to live
   - Maximum order size limit
   - Daily loss limit circuit breaker
   - Rate limiting on order endpoints
4. **WebSocket Auth**: Validate session tokens on WS connection
5. **CORS**: Restrict to frontend origin only
