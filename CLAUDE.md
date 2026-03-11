# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Elder Trading System — a full-stack trading platform implementing Alexander Elder's Triple Screen methodology for Indian markets (NSE/BSE/MCX). FastAPI backend + Next.js 16 frontend with TradingView charts, Angel One broker integration, paper/live trading, real-time pipeline, and 10 technical indicators.

## Commands

### Backend
```bash
# Dev server (from backend/)
cd backend && uvicorn app.main:app --reload --port 8000

# All tests (from project root)
pytest tests/

# Single test file
pytest tests/test_golden_reference.py

# Single test by name
pytest -k "test_ema_values" tests/

# Verbose output
pytest tests/ -v
```

### Frontend
```bash
# Dev server (from frontend/, runs on port 3001)
cd frontend && npm run dev

# Build
cd frontend && npm run build

# Lint
cd frontend && npm run lint

# E2E tests (requires both backend + frontend running)
cd frontend && npx playwright test

# Single E2E test file
cd frontend && npx playwright test e2e/dashboard.spec.ts

# Single E2E test by name
cd frontend && npx playwright test -g "paper order"
```

## Architecture

### Backend (`backend/app/`, port 8000)

FastAPI with 5 API routers (`api/charts.py`, `api/trading.py`, `api/scanner.py`, `api/indicators.py`, `api/strategy.py`). Entry point: `main.py`. Two WebSocket endpoints: `/ws/market` (raw ticks) and `/ws/pipeline` (structured events).

**Indicator Engine** (`indicators/`): 10 indicators inheriting from `BaseIndicator` in `base.py`. Computed via `/api/indicators/compute`. Supports `screen` param (1/2/3) for selective computation per timeframe.

**Trading** (`trading/`): Paper mode (in-memory order book, instant fills) and Live mode (Angel One SmartAPI). Controlled by `TRADING_MODE` env var. Paper trades have write-through to DB for persistence across restarts.

**Risk** (`risk/`): Position sizer (2% rule), circuit breaker (6% rule), SafeZone stops.

**Strategy** (`strategy/`): Triple Screen analysis with A/B/C/D trade grading. Signal scoring (65+ threshold). Cross-timeframe validator for multi-screen signal confirmation.

**Broker** (`broker/`): Angel One SmartAPI with 3 API key sets (trading/historical/feed). TOTP auth. Falls back to demo data (Brownian motion OHLCV in `api/demo_data.py`) after 2 consecutive broker failures.

### Pipeline (`backend/app/pipeline/`)

Real-time trading pipeline that ties everything together per tracked symbol:

```
Tick → CandleBuilder → IndicatorEngine → TripleScreen → Risk Gate → Signal → DB + WebSocket broadcast
```

- `__init__.py` — `PipelineManager` singleton: routes ticks to `AssetSession` by token, manages start/stop tracking
- `asset_session.py` — Core orchestrator per symbol: candle buffers, indicator computation, signal evaluation, auto-execution (paper) or alert (live)
- `candle_builder.py` — Converts ticks to OHLCV bars per timeframe, handles NSE market hours (9:15-15:30 IST), volume delta from cumulative
- `indicator_engine.py` — Programmatic wrapper for all 10 indicators (non-HTTP), supports screen-based filtering
- `db_persistence.py` — Async CRUD for instruments, candles, signals, orders, positions, trades
- `utils.py` — Shared helpers: `last_non_null()`, `slope_of_last()`, `trend_of_last()`

Pipeline API endpoints are under `/api/strategy/pipeline/` (start, stop, status, signals, analysis).

### WebSocket Architecture

- `/ws/market` — Raw tick broadcast for legacy compatibility (used by WatchlistPanel for live quotes)
- `/ws/pipeline` — Structured bidirectional events:
  - Server → Client: `candle`, `running_bar`, `indicators`, `signal`, `trade_alert`, `order`, `pipeline_status`, `heartbeat`
  - Client → Server: `start_tracking`, `stop_tracking`, `get_status`

### Frontend (`frontend/src/`, port 3001)

Next.js 16 + React 19 + Tailwind CSS v4. Charts use TradingView Lightweight Charts v5.

**Layout**: Sidebar-based multi-view navigation. Page (`app/page.tsx`) renders a left sidebar with icon buttons and a content area that switches between views.

**Views** (sidebar `ViewId`): `dashboard` (Overview stats/positions/orders/signal), `charts` (TradingView + ThreeScreenView), `trades` (order form + positions + orders), `signals` (Triple Screen analysis), `risk` (risk overview + position sizer), `portfolio` (funds + watchlist), `settings`.

**State** (`store/useTradingStore.ts`): Zustand store with 5 slices — Asset (symbol/exchange/interval/token), MarketData (candles/indicators/loading), Pipeline (WS status/freshness/trading mode), Signals (signal list/active signal/triple screen), Trades (positions/orders). Components read from store directly (no prop drilling).

**WebSocket** (`lib/websocketManager.ts`): Non-React class managing `/ws/pipeline` + `/ws/market` connections. Dispatches events to Zustand store via `getState()`. Auto-reconnect with exponential backoff. 30s heartbeat timeout marks data as stale.

**Bootstrap** (`hooks/usePipelineInit.ts`): Called once in `page.tsx`. Initializes WebSocketManager, fetches initial candles + indicators, polls health every 30s.

**API client** (`lib/api.ts`): Resilient fetch with timeout (10s), retry (2x with backoff), typed responses. Base URL from `NEXT_PUBLIC_API_URL` or `http://localhost:8000`.

## Critical Conventions

### Import paths
- **Backend code** uses `app.` prefix (e.g., `from app.indicators.ema import EMAIndicator`)
- **Tests** use `backend.app.` prefix (e.g., `from backend.app.indicators.ema import EMAIndicator`)
- Some modules (`stops.py`, `triple_screen.py`, `indicators.py`, `strategy.py`) have try/except to handle both import styles

### Numeric gotchas
- Always wrap numpy boolean comparisons in `bool()` when returning from functions
- `AutoEnvelope` uses `ddof=0` (population standard deviation) — this is intentional and configurable
- `SafeZone` uses prefix-sum O(N) optimization — do not revert to naive O(N²) loop
- `ElderThermometer` uses `CLASSIC_PERIOD=13` constant
- Golden reference tests use `atol=1e-6` tolerance for float comparisons

### Test data
- `tests/golden_data.py` contains a deterministic 50-bar OHLCV dataset used across all golden reference tests
- E2E tests use deterministic waits (API response + DOM element checks via `frontend/e2e/helpers.ts`), not `waitForTimeout`
- E2E navigation: use `goToCharts(page)`, `goToTrades(page)`, `goToRisk(page)`, `goToPortfolio(page)` helpers to navigate sidebar views

### Frontend path alias
- `@/*` maps to `./src/*` in tsconfig

### Signal dedup
- Pipeline uses both in-memory key tracking (`_last_signal_key`) and DB-level duplicate detection to prevent duplicate signals on restart

## Environment Variables

Loaded from `.env` at project root. Key vars:
- `ANGEL_API_KEY`, `ANGEL_SECRET_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_CLIENT_PASSWORD`, `ANGEL_TOTP_SECRET` — primary broker
- `ANGEL_HIST_API_KEY`, `ANGEL_HIST_API_SECRET` — historical data
- `ANGEL_FEED_API_KEY`, `ANGEL_FEED_API_SECRET` — WebSocket feed
- `TRADING_MODE` — `PAPER` (default) or `LIVE`
- `TELEGRAM_BOT_TOKEN` — notifications

## Database

SQLite via SQLAlchemy + aiosqlite. File: `backend/elder_trading.db` (relative to where uvicorn is started). Tables: instruments, candles, signals, orders, positions, trades, config, portfolio_risk.

## Reference Material

- `references/elders-3screen/` — Reference implementation (indicator source code)
- `plan/` — Architecture docs, methodology docs, gaps analysis, and roadmap
