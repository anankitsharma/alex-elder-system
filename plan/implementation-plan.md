# Alexander Elder Trading System — Implementation Plan (Indian Markets)

## Context

Build a production-grade, full-auto trading system for **Indian markets (NSE/BSE/MCX)** based on Alexander Elder's methodology, using **Angel One SmartAPI** for data streaming + order execution. The system must have a beautiful, fully configurable dashboard, robust signal generation with minimal false positives/negatives, live charts with all Elder indicators, market scanner, backtesting, risk management (2%/6% rules), and trade journaling.

**Key requirements:**
- Indian markets only via Angel One SmartAPI
- **Asset classes**: Equities (NSE/BSE stocks), F&O (Futures & Options on NSE), Commodities (MCX)
- **Scanner universe**: NIFTY 500 stocks + active F&O contracts + MCX commodities
- Full auto-trading with paper/live mode toggle and safety checks
- All features: live charts, scanner, backtesting, risk dashboard
- Robust signals — multi-confirmation, minimal false positives/negatives
- Everything configurable from the frontend UI
- Angel One SmartAPI credentials ready (API Key, Client ID, Password, TOTP secret)

---

## Project Structure

```
alex-elder/
├── plan/                                    # Research & documentation
│   ├── implementation-plan.md               # THIS FILE
│   ├── elder-methodology.md                 # Elder's complete trading methodology
│   ├── indicators-reference.md              # All indicator formulas & parameters
│   ├── tech-stack-research.md               # Technology decisions & alternatives
│   └── architecture.md                      # System architecture with diagrams
│
├── backend/                                 # Python FastAPI
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                         # FastAPI app + startup/shutdown
│   │   ├── config.py                       # Settings (Pydantic BaseSettings)
│   │   ├── database.py                     # SQLAlchemy async setup
│   │   │
│   │   ├── models/                         # DB models + Pydantic schemas
│   │   │   ├── market.py                   # OHLCV, tick data models
│   │   │   ├── signal.py                   # Signal/alert models
│   │   │   ├── trade.py                    # Order, position, trade models
│   │   │   └── config.py                   # Strategy config models
│   │   │
│   │   ├── broker/                         # Angel One SmartAPI integration
│   │   │   ├── angel_client.py             # SmartAPI wrapper (login, TOTP, tokens)
│   │   │   ├── websocket_feed.py           # SmartWebSocketV2 live data streaming
│   │   │   ├── orders.py                   # Order placement/modify/cancel/GTT
│   │   │   ├── instruments.py             # Scrip master / token mapping
│   │   │   └── historical.py              # Historical candle data fetcher
│   │   │
│   │   ├── indicators/                     # Elder indicator engine
│   │   │   ├── __init__.py
│   │   │   ├── impulse.py                 # Impulse System (13-EMA + MACD-H)
│   │   │   ├── elder_ray.py               # Bull Power / Bear Power
│   │   │   ├── force_index.py             # Force Index (2-day, 13-day)
│   │   │   ├── safezone.py                # SafeZone Stops
│   │   │   ├── autoenvelope.py            # AutoEnvelope channels
│   │   │   ├── triple_screen.py           # Triple Screen orchestrator
│   │   │   ├── divergence.py              # MACD-H divergence detector
│   │   │   └── pipeline.py               # Indicator calculation pipeline
│   │   │
│   │   ├── strategy/                       # Signal generation (robust)
│   │   │   ├── signals.py                 # Multi-confirmation signal engine
│   │   │   ├── scanner.py                 # NSE/BSE market scanner
│   │   │   ├── filters.py                # False positive reduction filters
│   │   │   └── screener.py               # Triple Screen screener
│   │   │
│   │   ├── risk/                           # Risk management
│   │   │   ├── position_sizer.py          # 2% rule
│   │   │   ├── portfolio_risk.py          # 6% rule
│   │   │   ├── stops.py                   # SafeZone + ATR stop management
│   │   │   └── circuit_breaker.py         # Emergency halt logic
│   │   │
│   │   ├── trading/                        # Order execution engine
│   │   │   ├── executor.py                # Auto-trade executor with safety
│   │   │   ├── paper_trader.py            # Paper trading simulator
│   │   │   ├── positions.py               # Position tracking + P&L
│   │   │   └── journal.py                # Trade journal + grading
│   │   │
│   │   ├── backtest/                       # Backtesting engine
│   │   │   ├── engine.py                  # Backtest runner
│   │   │   ├── data_loader.py             # Historical data (jugaad-data)
│   │   │   └── metrics.py                # Performance metrics
│   │   │
│   │   ├── api/                            # REST API routes
│   │   │   ├── charts.py                  # Chart data endpoints
│   │   │   ├── signals.py                 # Signal endpoints
│   │   │   ├── trading.py                 # Order/position endpoints
│   │   │   ├── backtest.py                # Backtest endpoints
│   │   │   ├── config.py                  # Configuration endpoints
│   │   │   └── scanner.py                 # Scanner endpoints
│   │   │
│   │   └── ws/                             # WebSocket routes
│   │       ├── market_stream.py           # Live price → frontend
│   │       └── signal_stream.py           # Live signals → frontend
│   │
│   └── tests/
│       ├── test_indicators.py
│       ├── test_signals.py
│       └── test_risk.py
│
├── frontend/                               # Next.js + React
│   ├── package.json
│   ├── next.config.js
│   ├── tailwind.config.ts
│   ├── src/
│   │   ├── app/                           # Next.js App Router pages
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx                   # Dashboard home
│   │   │   ├── triple-screen/page.tsx     # Triple Screen view
│   │   │   ├── scanner/page.tsx           # Market scanner
│   │   │   ├── backtest/page.tsx          # Backtesting
│   │   │   ├── journal/page.tsx           # Trade journal
│   │   │   ├── risk/page.tsx              # Risk dashboard
│   │   │   └── settings/page.tsx          # Configuration
│   │   │
│   │   ├── components/
│   │   │   ├── charts/                    # TradingView Lightweight Charts
│   │   │   ├── dashboard/                 # KPI cards, positions, signals
│   │   │   ├── trading/                   # Order panel, mode toggle
│   │   │   ├── scanner/                   # Scanner table, impulse grid
│   │   │   ├── settings/                  # Config forms
│   │   │   └── ui/                        # shadcn/ui components
│   │   │
│   │   ├── hooks/                         # useWebSocket, useMarketData, useSignals
│   │   ├── lib/                           # API + WS clients
│   │   └── store/                         # Zustand stores
│   │
│   └── public/
│
└── docker-compose.yml                      # Redis (optional for dev)
```

---

## Implementation Phases

### Phase 1: Foundation (Backend Core + Angel One)
1. Scaffold FastAPI project with config, DB, models
2. Implement Angel One SmartAPI client (login, session, TOTP)
3. Implement SmartWebSocketV2 live data feed
4. Implement historical candle data fetcher
5. Build instrument master loader (scrip master JSON → token mapping)
6. Set up SQLite database schema
7. Create basic REST API endpoints (health, instruments, candles)

### Phase 2: Indicator Engine
1. Implement indicator pipeline using pandas-ta as base
2. Build custom Elder indicators:
   - Impulse System (13-EMA slope + MACD-H slope → color)
   - SafeZone Stops (22-day lookback, 2.5x factor, DM-based)
   - AutoEnvelope (EMA(22) ± 2.7 SD over 100 bars)
   - Triple Screen orchestrator (multi-timeframe)
   - MACD-H divergence detector (with zero-line cross validation)
3. Use pandas-ta for standard indicators: EMA, MACD, Stochastic, RSI, ATR, Force Index
4. Build indicator calculation pipeline (raw OHLCV → all indicators computed)

### Phase 3: Signal Engine & Risk Management
1. Build multi-confirmation signal generator
2. Implement signal scoring system (0-100 confidence)
3. Build market scanner (scan NIFTY 500 + F&O + MCX for Elder setups)
4. Implement false positive filters (volume, liquidity, volatility, cooldown)
5. Build 2% rule position sizer
6. Build 6% rule portfolio risk tracker
7. Implement SafeZone stop calculator + ATR stop fallback
8. Build circuit breaker (halt trading on excessive losses)

### Phase 4: Frontend Dashboard
1. Scaffold Next.js project with shadcn/ui + Tailwind
2. Build main chart component (lightweight-charts + Impulse color-coded candles)
3. Build indicator sub-panes (MACD-H, Force Index, Elder-Ray, Stochastic)
4. Build Triple Screen 3-panel synchronized view
5. Build KPI dashboard (P&L cards, risk %, win rate via Tremor)
6. Build positions table, equity curve
7. Build WebSocket connection for live price updates
8. Build signal alerts feed (real-time)

### Phase 5: Trading Execution
1. Build paper trading simulator (tracks virtual orders + P&L)
2. Build live order executor with Angel One SmartAPI
3. Build paper/live mode toggle with safety confirmation dialog
4. Implement GTT orders for automated stop losses
5. Build order modification/cancellation
6. Build position tracking with live P&L from WebSocket prices

### Phase 6: Scanner + Backtesting
1. Build market scanner for all asset classes:
   - **Equities**: Scan NIFTY 500 stocks for Elder setups
   - **F&O**: Scan active futures/options for Impulse + Triple Screen signals
   - **MCX**: Scan commodities (Gold, Silver, Crude, NG, Copper) for Elder setups
2. Build Impulse System color heatmap grid (grouped by sector/asset class)
3. Build backtest engine using historical data (jugaad-data + Angel One historical)
4. Implement performance metrics (Sharpe, Sortino, max drawdown, win rate, profit factor, CAGR)
5. Build backtest results visualization (equity curve + trade markers on chart)
6. F&O specific: Lot size handling, margin calculations, expiry awareness

### Phase 7: Configuration + Polish
1. Build settings pages (indicator params, risk rules, broker keys, alerts)
2. Make all indicator parameters configurable via API + stored in DB
3. Make signal thresholds configurable from UI
4. Add structured logging (loguru)
5. Add error handling and reconnection logic for WebSocket
6. Add trade journal with automatic grading

---

## Signal Robustness — Reducing False Positives/Negatives

### Multi-Confirmation Approach
Every signal requires **minimum 3 confirmations** before triggering:

1. **Triple Screen Alignment**: Weekly trend + daily pullback + intraday entry timing
2. **Impulse System Filter**: Never buy on red bars, never sell on green bars
3. **Volume Confirmation**: Force Index must confirm (2-day FI negative for buy setups in uptrend)
4. **Value Zone Check**: Price near EMA(13)/EMA(26) zone, not overextended
5. **Elder-Ray Validation**: Bear Power below zero but rising (for longs)

### Additional Filters
- **MACD-H Divergence Bonus**: Extra weight when divergence present (with zero-line cross)
- **ATR Volatility Filter**: Skip signals in extremely low volatility (< 0.5× 20-day avg ATR)
- **Market Hours Filter**: Only during NSE trading hours (9:15 AM - 3:30 PM IST)
- **Circuit Breaker Filter**: Skip stocks hitting circuit limits
- **Liquidity Filter**: Minimum average daily volume threshold
- **Signal Cooldown**: Minimum gap between repeated signals on same stock
- **Trend Strength Threshold**: EMA slope must exceed minimum angle

### Signal Scoring System (0-100)
| Confirmation | Score |
|-------------|-------|
| Weekly trend aligned (MACD-H slope) | +20 |
| Daily pullback detected (FI/Elder-Ray) | +20 |
| Impulse System allows trade | +15 |
| Volume confirms (13-day FI direction) | +10 |
| In Value Zone | +10 |
| MACD-H divergence present | +15 |
| Elder-Ray divergence | +10 |

**Minimum score to trade: 65** (configurable from UI)

---

## Verification Plan

1. **Indicator Accuracy**: Compare against TradingView for RELIANCE, INFY, TCS — within 0.01%
2. **Signal Correctness**: Verify 20+ signals match Elder's rules on historical data
3. **False Positive Rate**: Target <30% false positive rate via backtest
4. **Risk Rules**: Unit test 2%/6% rules with edge cases
5. **WebSocket Stability**: 50 instruments, 1+ hour without drops
6. **Paper Trading Cycle**: Full scan → signal → order → stop → exit cycle
7. **UI Responsiveness**: Triple Screen with 3 panels + 4 sub-panes smooth
8. **Backtest Validation**: NIFTY 50 stocks 2023-2025, realistic metrics
9. **F&O Handling**: Lot sizes, margins, expiry rollover correct
10. **MCX Handling**: Commodity contracts data + indicators work correctly
