# Technology Stack Research & Decisions

## Final Stack Selection

### Backend: Python 3.12+ / FastAPI
### Frontend: Next.js 15 / React 18 / TypeScript
### Broker: Angel One SmartAPI
### DB: SQLite (dev) → PostgreSQL (prod)
### Charts: TradingView Lightweight Charts

---

## 1. Backend Packages

| Package | Version | Purpose | Install |
|---------|---------|---------|---------|
| fastapi | 0.115+ | REST API + WebSocket server | `pip install fastapi[standard]` |
| uvicorn | latest | ASGI server | `pip install uvicorn` |
| smartapi-python | 1.5.5 | Angel One broker + data | `pip install smartapi-python` |
| pandas-ta | 0.3.14b1 | 150+ technical indicators (pure Python) | `pip install pandas-ta` |
| pandas | 2.x | Data manipulation | `pip install pandas` |
| numpy | 2.x | Numerical computing | `pip install numpy` |
| pyotp | latest | TOTP generation for Angel One login | `pip install pyotp` |
| jugaad-data | latest | NSE historical data (free) | `pip install jugaad-data` |
| redis | latest | Pub/sub event bus + cache | `pip install redis` |
| sqlalchemy | 2.x | Async ORM | `pip install sqlalchemy` |
| aiosqlite | latest | Async SQLite driver | `pip install aiosqlite` |
| loguru | latest | Structured logging | `pip install loguru` |
| apscheduler | latest | Scheduled tasks | `pip install apscheduler` |
| fastapi-mcp | 0.2.0 | Expose API as MCP tools | `pip install fastapi-mcp` |

### Why FastAPI over Django/Flask
- **Async native**: Built on ASGI, handles WebSocket streaming natively
- **Performance**: 15k-20k req/s (vs Flask ~5k, Django ~3k)
- **Auto docs**: Swagger/OpenAPI generated automatically
- **Pydantic**: Built-in data validation
- **WebSocket**: First-class support for real-time data streaming

### Why pandas-ta over TA-Lib
- **Pure Python**: No C library dependency (TA-Lib requires complex C installation on Windows)
- **150+ indicators**: EMA, MACD, Stochastic, RSI, ATR, Williams %R all included
- **Pandas native**: Works as DataFrame extension (`df.ta.ema(length=13)`)
- **Actively maintained**: Regular updates

---

## 2. Frontend Packages

| Package | Purpose | Install |
|---------|---------|---------|
| next | React framework (App Router) | `npx create-next-app@latest` |
| typescript | Type safety | included with Next.js |
| lightweight-charts | TradingView candlestick charts (19k+ stars) | `npm install lightweight-charts` |
| lightweight-charts-react-wrapper | React components | `npm install lightweight-charts-react-wrapper` |
| shadcn/ui | Beautiful UI components (Tailwind-based) | `npx shadcn@latest init` |
| @tremor/react | Analytics dashboard components | `npm install @tremor/react` |
| tailwindcss | Styling | included with Next.js |
| react-use-websocket | WebSocket hook | `npm install react-use-websocket` |
| @tanstack/react-query | Data fetching + caching | `npm install @tanstack/react-query` |
| react-hook-form | Form state management | `npm install react-hook-form` |
| zod | Schema validation | `npm install zod` |
| @hookform/resolvers | Zod + React Hook Form bridge | `npm install @hookform/resolvers` |
| zustand | State management (3KB) | `npm install zustand` |

### Why Next.js over Vite/CRA
- **App Router**: Server components reduce bundle size
- **API routes**: Can proxy backend calls if needed
- **Vercel deployment**: One-click deploy
- **Built-in optimizations**: Image, font, code splitting

### Why shadcn/ui + Tremor
- **shadcn/ui** (50KB): Copy-paste components, full control, Tailwind native
- **Tremor** (200KB): Pre-built KPI cards, charts, data tables — purpose-built for analytics dashboards
- Combined still lighter than Ant Design Pro alone
- Both use Tailwind CSS for consistent styling

### Why TradingView Lightweight Charts
- **Industry standard** for financial charting
- **Apache 2.0 license** (free for commercial use)
- **Smallest and fastest** financial HTML5 canvas charts
- **Rich plugin system** for custom indicators
- Stays responsive with thousands of bars + multiple updates/sec

---

## 3. Angel One SmartAPI Details

### Official SDK: `smartapi-python` (v1.5.5)
- GitHub: https://github.com/angel-one/smartapi-python
- PyPI: https://pypi.org/project/smartapi-python/
- 53 releases since Oct 2020, actively maintained

### Authentication
```python
from SmartApi import SmartConnect
import pyotp

obj = SmartConnect(api_key="YOUR_API_KEY")
totp = pyotp.TOTP("YOUR_TOTP_SECRET").now()
data = obj.generateSession("CLIENT_ID", "PASSWORD", totp)
feed_token = obj.getfeedToken()
```

### WebSocket (SmartWebSocketV2)
- Endpoint: `wss://smartapisocket.angelone.in/smart-stream`
- Modes: LTP | QUOTE (OHLC+vol) | SNAP_QUOTE (full depth)
- Max 3 concurrent connections per account
- Heartbeat: 10-second interval
- Exchange codes: NSE=1, NFO=2, BSE=3, MCX=5

### Historical Data
- Intervals: ONE_MINUTE, FIVE_MINUTE, FIFTEEN_MINUTE, THIRTY_MINUTE, ONE_HOUR, ONE_DAY
- Rate limited — must cache aggressively

### Order Types
- MARKET, LIMIT, SL (Stop Loss), SL-M (Stop Loss Market)
- AMO (After Market Orders)
- GTT (Good Till Triggered) — perfect for automated stop losses
- Modify/Cancel existing orders

### Instrument Master
- JSON endpoint: `https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json`
- Maps symbol names → exchange tokens
- Filter by exchange segment for NIFTY 500, F&O, MCX

---

## 4. Data Sources

| Source | Use Case | Cost |
|--------|----------|------|
| Angel One SmartAPI | Live streaming + historical (all exchanges) | Free with account |
| jugaad-data | NSE historical data backup, no auth needed | Free |
| Angel One Scrip Master | Instrument/token mapping | Free |

### jugaad-data
- Pure Python, no API key required
- Built for new NSE website
- Integrated caching
- Live quotes + historical data + derivatives + option chains

---

## 5. MCP Servers & Plugins

| Tool | Purpose | Value |
|------|---------|-------|
| fastapi-mcp | Expose FastAPI endpoints as MCP tools for Claude | Lets Claude interact with our API directly |
| magic-mcp (21st.dev) | AI-powered React component generation | Speeds up UI development 2-3x |
| financial-datasets MCP | Supplementary financial data | Additional market data sources |
| trading-indicator-plugins | 33 commands + 10 agents for indicator development | Accelerates indicator coding |

---

## 6. Reference Repos

| Repo | Stars | What to Reuse |
|------|-------|---------------|
| [angel-one/smartapi-python](https://github.com/angel-one/smartapi-python) | Official | WebSocket V2, orders, auth |
| [ANANDAPADMANABHA/Trade-master](https://github.com/ANANDAPADMANABHA/Trade-master) | — | Angel One algo bot, risk mgmt |
| [pkjmesra/PKScreener](https://github.com/pkjmesra/PKScreener) | 1k+ | NSE screener, pattern detection |
| [marketcalls/openalgo](https://github.com/marketcalls/openalgo) | — | Full-stack algo platform |
| [Kiranism/next-shadcn-dashboard-starter](https://github.com/Kiranism/next-shadcn-dashboard-starter) | 2k+ | Dashboard template |
| [lgbarn/trading-indicator-plugins](https://github.com/lgbarn/trading-indicator-plugins) | — | Indicator dev tools |
| [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | 47.5k | Bot architecture patterns |
| [buzzsubash/algo_trading_strategies_india](https://github.com/buzzsubash/algo_trading_strategies_india) | — | Indian market strategies |

---

## 7. Database Strategy

### Development: SQLite (via aiosqlite)
- Zero setup, file-based
- Perfect for single-user development
- Python built-in support

### Production: PostgreSQL (via asyncpg)
- Concurrent write support
- TimescaleDB extension for time-series optimization
- Better for multi-user / multi-process

### Schema (Key Tables)
- `instruments` — scrip master cache
- `candles` — OHLCV historical data
- `signals` — generated signals with scores
- `orders` — order history
- `positions` — open/closed positions
- `trades` — trade journal entries with grades
- `config` — strategy/indicator parameters

---

## 8. Real-Time Architecture

```
Angel One WebSocket (SmartWebSocketV2)
  → Python async consumer (asyncio)
  → Indicator calculation (pandas-ta + custom)
  → Signal scoring engine
  → Redis pub/sub (distribute events)
  → FastAPI WebSocket server
  → React frontend (react-use-websocket)
  → TradingView Lightweight Charts (render)
```

### Key Patterns
- **Circular Buffer** (`collections.deque`) for OHLCV sliding window
- **asyncio.Queue** for decoupled processing stages
- **Redis pub/sub** for event distribution to multiple consumers
- **WebSocket reconnection** with exponential backoff
