# WebSocket & Live Data Integration Plan

## Current State (What Already Exists)

**Backend — fully built:**
- `pipeline/candle_builder.py` — tick → OHLCV aggregation (all timeframes, NSE market hours aware)
- `pipeline/indicator_engine.py` — all 10 indicators, screen-aware computation
- `pipeline/asset_session.py` — full orchestrator: CandleBuilder → Indicators → TripleScreen → Risk → Execute
- `pipeline/__init__.py` — PipelineManager routes ticks to AssetSessions by token
- `pipeline/db_persistence.py` — async CRUD for candles, signals, orders, positions
- `ws/market_stream.py` — dual WebSocket: `/ws/market` (raw ticks) + `/ws/pipeline` (structured events)
- `broker/websocket_feed.py` — Angel One SmartWebSocketV2 with auto-reconnect
- `main.py` — wires `market_feed.add_callback(pipeline_manager.on_tick)` on startup

**Frontend — plumbing exists:**
- `lib/websocketManager.ts` — connects to both WS endpoints, dispatches to Zustand
- `store/useTradingStore.ts` — `appendCandle()`, `updateLastCandle()`, signal/tripleScreen handling
- `hooks/usePipelineInit.ts` — bootstraps WS + initial REST data + health polling

## The Problem: Nothing Is Wired Together

1. **Frontend never tells backend to track a symbol.** `start_tracking` WebSocket action exists but is never sent. No AssetSession ever starts.
2. **Three-screen view ignores WebSocket.** Each screen panel uses `useCandles` + `useIndicators` (REST polling). WebSocket-delivered candles/indicators are discarded.
3. **No gap detection.** If system was offline 2 hours, those 2 hours of candles are just missing forever.
4. **No backend heartbeat.** Frontend has heartbeat timeout (30s → stale) but backend never sends heartbeats.
5. **Health endpoint is blind.** `/api/health` returns static config, doesn't report broker/feed status.
6. **Indicator WS events are placeholders.** `websocketManager.ts` receives `indicators` events but just logs them.
7. **Single-chart view doesn't do incremental updates.** TradingViewChart uses full `setData()`, not `series.update()`.

## Architecture (How Reference Does It)

From `references/elders-3screen`:

```
Angel One WebSocket Feed
    ↓ (ticks)
CandleBuilder (1m → 5m → 15m → 1h → 4h → 1d)
    ↓ (completed bar)
DB write (atomic: candle + indicators together)
    ↓
WebSocket broadcast to subscribed clients
    ↓
Frontend: merge into existing chart data
    - Same timestamp → update in-progress bar
    - New timestamp → append completed bar
```

Key patterns from reference:
- **Smart backfill**: compare `last_candle_time` vs `now`, fetch only missing range
- **Batch DB writes**: queue 10 candles, flush every 1s
- **Pub-sub subscriptions**: only broadcast to clients tracking that symbol
- **Circuit breaker on feed**: 5 failures → 60s cooldown → retry
- **Partial candle marking**: `is_current: true` for in-progress bars

---

## Implementation Plan

### Step 1: Backend — Heartbeat + Health Enhancement

**File: `backend/app/ws/market_stream.py`**
- Add heartbeat loop: every 15s, broadcast `{"type": "heartbeat", "ts": "..."}` to pipeline clients
- Start heartbeat task when first pipeline client connects, stop when last disconnects

**File: `backend/app/main.py`**
- `/api/health` returns broker status: `feed_connected`, `feed_last_data_age`, `broker_online`, `active_sessions`
- Import `market_feed.is_connected` and `market_feed.last_data_age` for real status

### Step 2: Backend — Gap Detection & Backfill

**File: `backend/app/pipeline/asset_session.py`**
- In `start()`, after loading historical: call `_detect_and_fill_gaps()`
- `_detect_and_fill_gaps(timeframe)`:
  1. Get last candle timestamp from DB for this instrument+timeframe
  2. Calculate expected candles between last_candle and now
  3. If gap > 0: fetch missing range from broker historical API
  4. Insert fetched candles, recompute indicators
- On reconnect (when feed comes back online): call gap fill for all active sessions

**File: `backend/app/pipeline/db_persistence.py`**
- `detect_candle_gaps()` already exists — wire it into AssetSession startup

### Step 3: Frontend — Auto-Track on Symbol Change

**File: `frontend/src/lib/websocketManager.ts`**
- Add `trackSymbol(symbol, exchange)` method: sends `start_tracking` action to pipeline WS
- Add `untrackSymbol(symbol, exchange)`: sends `stop_tracking`
- On reconnect: re-send `start_tracking` for current symbol (resubscribe pattern from reference)
- Store `currentTrackedSymbol` to know what to resubscribe

**File: `frontend/src/store/useTradingStore.ts`**
- `setAsset()`: after REST fetch, also call `wsManager.trackSymbol(symbol, exchange)`
- Store `wsManager` reference in the store (or as module singleton)

**File: `frontend/src/hooks/usePipelineInit.ts`**
- After `ws.connect()`, send `start_tracking` for initial symbol (NIFTY:NFO)
- Expose `wsManager` so page.tsx can pass it to store or components

### Step 4: Frontend — Use WebSocket Indicators Directly

**File: `frontend/src/lib/websocketManager.ts`**
- `indicators` handler: instead of placeholder, call `store.setIndicators(data)` if timeframe matches current interval
- Add `setIndicators(data)` to store that merges with existing indicator data

**File: `frontend/src/store/useTradingStore.ts`**
- Add `setIndicators(data: IndicatorData)` action
- When WS delivers indicators, set directly (no REST round-trip)
- Keep REST `fetchIndicators()` as fallback for initial load and reconnect

### Step 5: Frontend — Incremental Chart Updates (TradingViewChart)

**File: `frontend/src/components/chart/TradingViewChart.tsx`**
- Store series refs (candlestick, volume, ema13, ema22, etc.)
- Watch store's `lastCandleTime` — when it changes:
  - If same timestamp as current last bar → `series.update()` (in-progress bar update)
  - If new timestamp → `series.update()` with new data point (auto-appends)
- This replaces full `setData()` for live updates — much more efficient
- Keep `setData()` for initial load and symbol changes only

### Step 6: Frontend — Three-Screen View WebSocket Integration

**File: `frontend/src/components/chart/ThreeScreenView.tsx`**
- Screen panels currently use independent `useCandles` + `useIndicators` hooks (REST)
- **Keep REST for initial load** (this works well with stagger and caching)
- **Add WebSocket overlay**: subscribe to pipeline events for the tracked symbol
- When `candle` event arrives with matching timeframe → append to that screen's data
- When `running_bar` event arrives → update last candle of matching screen
- This means screens auto-update without re-fetching

**Implementation approach:**
- Create `useLiveCandles(symbol, exchange, timeframe)` hook:
  - Subscribes to Zustand store's pipeline events filtered by timeframe
  - Returns `{ appendCandle, updateRunning }` callbacks
  - Each Screen panel calls this hook alongside existing `useCandles`

### Step 7: Backend — Feed Subscription Management

**File: `backend/app/broker/websocket_feed.py`**
- When `start_tracking` is called, ensure the symbol's token is subscribed on Angel One feed
- `market_feed.subscribe(token, exchange, mode="QUOTE")` — already exists
- Wire: `pipeline_manager.start_tracking()` → `market_feed.subscribe(token)`

**File: `backend/app/pipeline/__init__.py`**
- In `start_tracking()`: after creating AssetSession, call `market_feed.subscribe(token, exchange)`
- In `stop_tracking()`: if no other session uses that token, unsubscribe

### Step 8: REST Polling Fallback

**File: `frontend/src/hooks/usePipelineInit.ts`**
- If pipeline WS disconnected > 60s AND api is online:
  - Start REST polling: fetch candles every 30s for current symbol
  - Show "STALE" indicator
  - Stop polling when WS reconnects

**File: `frontend/src/store/useTradingStore.ts`**
- Add `startPolling()` / `stopPolling()` actions
- Polling fetches candles + indicators via REST, updates store

---

## Data Flow After Implementation

### Live Mode (broker connected):
```
User selects NIFTY:NFO
    ↓
Frontend: store.setAsset("NIFTY", "NFO")
    ├→ REST: fetchCandles() + fetchIndicators() → initial chart data
    └→ WS: sendPipelineAction("start_tracking", {symbol: "NIFTY", exchange: "NFO"})
        ↓
Backend: pipeline_manager.start_tracking("NIFTY", "NFO")
    ├→ Resolve token → subscribe on Angel One feed
    ├→ Load historical data → detect gaps → backfill
    ├→ Compute indicators for all 3 screens
    └→ Broadcast pipeline_status
        ↓
Angel One ticks arrive every ~1s
    ↓
AssetSession.on_tick(tick)
    ├→ CandleBuilder aggregates into bars
    ├→ Running bar broadcast → frontend updates in-progress candle
    └→ On bar close:
        ├→ Persist to DB
        ├→ Compute indicators
        ├→ Broadcast {type: "candle", timeframe, candle}
        ├→ Broadcast {type: "indicators", timeframe, data}
        ├→ TripleScreen analysis
        └→ Broadcast {type: "signal", analysis}
            ↓
Frontend receives events via /ws/pipeline
    ├→ candle → store.appendCandle() or screen panel update
    ├→ running_bar → store.updateLastCandle()
    ├→ indicators → store.setIndicators()
    ├→ signal → store.setTripleScreen() → SignalPanel updates
    └→ trade_alert → toast notification
```

### Offline/Demo Mode:
```
Backend broker login fails → offline mode
    ↓
Frontend: REST fetch returns source="demo"
    ├→ Show "DEMO" badge
    ├→ Charts render with synthetic data
    └→ Pipeline WS connects but no ticks arrive
        ↓
Heartbeat timeout (30s) → dataFreshness = "stale"
    ↓
If API still online: REST polling fallback (every 30s)
```

### System Restart / Gap Fill:
```
System comes back online after 2h downtime
    ↓
AssetSession.start() → _detect_and_fill_gaps()
    ↓
For each timeframe:
    ├→ Last DB candle: 2026-03-11 11:45:00
    ├→ Current time: 2026-03-11 13:45:00
    ├→ Gap: 2 hours of 15m candles = 8 missing bars
    ├→ Fetch from broker: historical API (11:45 → 13:45)
    ├→ Insert to DB + append to buffer
    └→ Recompute indicators on full buffer
        ↓
Live ticks resume → normal pipeline continues
```

---

## Implementation Order

```
Step 1: Backend heartbeat + health (15 min)     — foundation
Step 2: Backend gap detection (30 min)           — data integrity
Step 3: Frontend auto-track (20 min)             — activates pipeline
Step 4: Frontend WS indicators (15 min)          — eliminates REST polling
Step 5: Incremental chart updates (30 min)       — smooth live display
Step 6: Three-screen WS integration (30 min)     — live multi-timeframe
Step 7: Feed subscription management (15 min)    — correct token routing
Step 8: REST polling fallback (15 min)           — resilience
```

Steps 1-3 are the critical path — they wire the pipeline end-to-end.
Steps 4-6 make it smooth and efficient.
Steps 7-8 add resilience.

## Files Modified

| File | Action | Step |
|------|--------|------|
| `backend/app/ws/market_stream.py` | MODIFY (heartbeat) | 1 |
| `backend/app/main.py` | MODIFY (health endpoint) | 1 |
| `backend/app/pipeline/asset_session.py` | MODIFY (gap fill) | 2 |
| `frontend/src/lib/websocketManager.ts` | MODIFY (trackSymbol, resubscribe) | 3 |
| `frontend/src/store/useTradingStore.ts` | MODIFY (setIndicators, wsManager ref) | 3, 4 |
| `frontend/src/hooks/usePipelineInit.ts` | MODIFY (auto-track, polling fallback) | 3, 8 |
| `frontend/src/components/chart/TradingViewChart.tsx` | MODIFY (incremental update) | 5 |
| `frontend/src/components/chart/ThreeScreenView.tsx` | MODIFY (WS overlay) | 6 |
| `backend/app/pipeline/__init__.py` | MODIFY (feed subscribe) | 7 |
| `backend/app/broker/websocket_feed.py` | No change needed (subscribe exists) | 7 |
