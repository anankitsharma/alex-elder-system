# How to Test — Elder Trading System Live Testing Guide

## Prerequisites

- Python 3.11+ with `pip install -r backend/requirements.txt`
- Node.js 18+ with `cd frontend && npm install`
- `.env` file at project root with Angel One API keys
- Playwright browsers: `cd frontend && npx playwright install chromium`

---

## 1. Start the System

### Terminal 1 — Backend
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Wait for these log lines:
```
All Angel One API sessions active
Market feed WebSocket starting in background thread
Market feed WebSocket connected
```

### Terminal 2 — Frontend
```bash
cd frontend
npm run dev
```

Open **http://localhost:3001** in your browser.

---

## 2. Verify System Health

### Quick API Check
Open in browser or curl:
```
http://localhost:8000/api/health
```

You should see:
```json
{
  "status": "ok",
  "trading_mode": "PAPER",
  "feed_connected": true,
  "broker_online": true,
  "active_sessions": 0
}
```

### Status Bar (Frontend)
At the top of the page, the **Pipeline Status Bar** should show:
- **LIVE** (green) — data feed is connected
- **Feed: ON** — Angel One WebSocket feed connected
- **WS: ON** — Pipeline WebSocket connected
- **PAPER** (amber badge) — trading mode

---

## 3. Test Single Chart View

1. Click **Charts** in the left sidebar (bar chart icon)
2. Default symbol is **NIFTY / NFO**
3. You should see:
   - Candlestick chart with EMA(13) yellow, EMA(22) purple overlays
   - SafeZone dashed lines (green = long stop, red = short stop)
   - Impulse coloring (green/red/blue candles)
   - MACD subchart with 4-color histogram
   - Force Index subchart
   - Elder-Ray subchart (bull green / bear red)
4. **LTP Price Line**: A blue dashed horizontal line showing the last traded price
5. Try switching intervals: `1d`, `1h`, `15m` from the interval selector

### During Market Hours
If market is open (NSE: 9:15-15:30 IST, MCX: 10:00-23:30 IST):
- Status bar should show **X tps** (ticks per second) with a pulsing green dot
- The last candle should update in real-time (running bar)
- No chart flicker — updates use incremental `series.update()` not full `setData()`

---

## 4. Test Three Screen View

1. On the Charts page, click **Three Screen** toggle (grid icon, top-left)
2. You should see 3 charts side by side:
   - **Screen 1 — Daily (Tide)**: Candle + EMA + MACD
   - **Screen 2 — Hourly (Wave)**: Candle + EMA + MACD + Force Index + Elder-Ray
   - **Screen 3 — 15min (Ripple)**: Candle + EMA + Force Index
3. Each screen has a **LIVE** indicator when receiving real-time data
4. Below the charts: **Signal Panel** showing Triple Screen analysis

### Zoom
- Click the expand icon (top-right of each screen) to zoom into a single screen
- Click minimize to return to 3-column view

---

## 5. Test Symbol Switching

1. Go to **Portfolio** view (briefcase icon in sidebar)
2. In the **Watchlist** panel, click on a symbol (RELIANCE, HDFCBANK, etc.)
3. The chart should reload with the new symbol
4. Status bar should show data loading, then return to LIVE
5. Pipeline will auto-track the new symbol via WebSocket

### Switch to GOLDM (MCX)
1. Click **GOLDM** in the watchlist
2. Timeframes should change to COMMODITY mode: 1d / 1h / 15m
3. In Three Screen view, screen labels should update accordingly

---

## 6. Test Pipeline Status

### API Endpoint
```
http://localhost:8000/api/strategy/pipeline/status
```

Shows all active sessions with:
- Symbol, exchange, token
- Screen timeframes
- Candle counts per timeframe
- Latest grade (A/B/C/D) and action (BUY/SELL/WAIT)

### Start/Stop Pipeline for a Symbol
```bash
# Start
curl -X POST http://localhost:8000/api/strategy/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"symbol":"GOLDM","exchange":"MCX"}'

# Check analysis
curl http://localhost:8000/api/strategy/pipeline/analysis/GOLDM?exchange=MCX

# Stop
curl -X POST http://localhost:8000/api/strategy/pipeline/stop \
  -H "Content-Type: application/json" \
  -d '{"symbol":"GOLDM","exchange":"MCX"}'
```

---

## 7. Test Triple Screen Analysis

```
http://localhost:8000/api/strategy/pipeline/analysis/NIFTY?exchange=NFO
```

Check the response has:
- **screen1**: tide (BULLISH/BEARISH), MACD histogram slope, impulse signal
- **screen2**: signal (BUY/SELL), Force Index, Elder-Ray, impulse
- **screen3**: entry_type (BUY_STOP/SELL_STOP), entry_price, stop_price
- **recommendation**: action, confidence %, grade (A/B/C/D)
- **validation**: is_valid, warnings, blocks

---

## 8. Test WebSocket Events

### Using Python
```python
import asyncio, websockets, json

async def listen():
    async with websockets.connect("ws://localhost:8000/ws/pipeline") as ws:
        # Receive pipeline_status on connect
        print(json.loads(await ws.recv()))

        # Track a symbol
        await ws.send(json.dumps({
            "action": "start_tracking",
            "symbol": "NIFTY",
            "exchange": "NFO"
        }))

        # Listen for events
        while True:
            msg = json.loads(await ws.recv())
            t = msg.get("type")
            if t == "heartbeat":
                print(f"Heartbeat: feed={msg['feed_connected']} age={msg['feed_last_data_age']}s")
            elif t == "running_bar":
                bar = msg["bar"]
                print(f"Running bar [{msg['timeframe']}]: {bar['close']}")
            elif t == "candle":
                print(f"New candle [{msg['timeframe']}]")
            elif t == "signal":
                a = msg["analysis"]
                print(f"Signal: grade={a['grade']} action={a['recommendation']['action']}")
            elif t == "indicators":
                print(f"Indicators [{msg['timeframe']}]: {list(msg['data'].keys())[:5]}...")
            else:
                print(f"Event: {t}")

asyncio.run(listen())
```

### Expected Events (during market hours)
| Event | Frequency | Description |
|-------|-----------|-------------|
| `pipeline_status` | On connect | Active sessions summary |
| `heartbeat` | Every 15s | Feed status + data age |
| `running_bar` | Every tick (~1/sec) | In-progress candle per timeframe |
| `candle` | On bar close | Completed candle |
| `indicators` | After candle close | Updated indicators |
| `signal` | After indicators | Triple Screen analysis |
| `trade_alert` | On actionable signal | BUY/SELL alert with entry/stop |
| `order` | On auto-execute (PAPER) | Paper order filled |

---

## 9. Test Backfill (Reconnection Recovery)

```python
import asyncio, websockets, json

async def test_backfill():
    async with websockets.connect("ws://localhost:8000/ws/pipeline") as ws:
        await ws.recv()  # pipeline_status

        await ws.send(json.dumps({
            "action": "backfill",
            "symbol": "NIFTY",
            "exchange": "NFO",
            "since": "2026-03-15T00:00:00"
        }))

        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] == "backfill_response":
                for tf, bars in msg["candles"].items():
                    print(f"  {tf}: {len(bars)} candles backfilled")
                break

asyncio.run(test_backfill())
```

---

## 10. Test Signals & Paper Trading

### View Generated Signals
```
http://localhost:8000/api/strategy/pipeline/signals?limit=10
```

### Place a Manual Paper Order
Go to **Trades** view → fill in quantity → click BUY or SELL.

### Check Positions
```
http://localhost:8000/api/trading/positions
```

### Check Orders
```
http://localhost:8000/api/trading/orders
```

---

## 11. Test Risk Management

Go to **Risk** view in the sidebar:
- **Risk Overview**: Shows 2% Rule (per-trade) and 6% Rule (portfolio)
- **Position Sizer**: Enter entry price, stop price, account equity → calculates shares

### API
```bash
# Position sizing
curl "http://localhost:8000/api/strategy/risk/position-size?entry=100&stop=95&equity=100000"

# Circuit breaker status
curl http://localhost:8000/api/strategy/risk/circuit-breaker
```

---

## 12. Run Automated Tests

### Backend (388 tests)
```bash
# From project root
pytest tests/ -v

# Just golden reference tests (indicator accuracy)
pytest tests/test_golden_reference.py -v

# Pipeline tests
pytest tests/ -k "pipeline" -v
```

### E2E (64 tests)
```bash
cd frontend
npx playwright test
npx playwright test --ui  # Interactive test runner
```

---

## Market Hours Quick Reference

| Market | Hours (IST) | Test Symbols |
|--------|-------------|--------------|
| NSE/NFO | 9:15 AM - 3:30 PM | NIFTY, RELIANCE, HDFCBANK |
| MCX | 10:00 AM - 11:30 PM | GOLDM |

**Outside market hours**: System works with historical data. Live ticks won't arrive but all charts, analysis, and signals work from stored candles. Feed status will show stale/disconnected.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `feed_connected: false` | Check `.env` for ANGEL_FEED_API_KEY. Broker may be down. |
| No ticks during market hours | Check MCX hours for GOLDM (evening). NSE is daytime only. |
| Charts blank | Check browser console for errors. Try refreshing. |
| `broker_online: false` | Angel One session expired. Restart backend. |
| WebSocket disconnects | Check status bar — should auto-reconnect with backfill. |
| "DEMO DATA" badge | Broker offline — system falls back to synthetic Brownian data. |
| Pipeline won't start | Check `curl http://localhost:8000/api/health` first. |
| Stale data | Click refresh button (↻) in status bar, or check feed age. |

---

## Architecture Flow (for reference)

```
Angel One Feed → SmartWebSocketV2 (background thread)
     ↓
  on_tick callback
     ↓
PipelineManager.on_tick() → routes by token
     ↓
AssetSession.on_tick()
     ↓
CandleBuilder (per timeframe) → running_bar broadcast
     ↓ (on bar close)
IndicatorEngine.compute_for_screen()
     ↓
TripleScreenAnalysis.analyze()
     ↓
Risk Gate (CircuitBreaker + PositionSizer)
     ↓
Signal → DB + WebSocket broadcast
     ↓ (if PAPER mode + actionable)
Auto-execute → Paper order + position
     ↓
Frontend WebSocket → Zustand store → Chart update()
```
